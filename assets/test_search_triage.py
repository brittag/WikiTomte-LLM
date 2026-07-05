#!/usr/bin/env python3
"""Unit tests for search_triage (no network)."""

import sys
import unittest
import csv
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_detector import (
    has_ai_generated_template,
    is_ai_generated_template_name,
    normalize_pageid,
    page_has_ai_generated_template,
)
from search_triage import (
    TRIAGE_COLUMNS,
    build_query,
    build_vocab_query,
    eligible_narrowers,
    enrich_result,
    format_triage_csv,
    foster_false_positive,
    parse_query_terms,
    pick_era,
    pick_random_search,
    resolve_search_params,
    section_header_hit,
    strip_html,
)


class TestQueryBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ai_detector import load_vocab
        cls.vocab = load_vocab()

    def test_build_query_quotes_phrase(self):
        q = build_query("crucial role", ["underscore", "emphasizing"])
        self.assertEqual(q, '"crucial role" underscore emphasizing')

    def test_build_query_preserves_existing_quotes(self):
        q = build_query('"crucial role"', ["underscore"])
        self.assertEqual(q, '"crucial role" underscore')

    def test_build_vocab_query(self):
        q = build_vocab_query(["delve", "underscore", "pivotal"])
        self.assertEqual(q, "delve underscore pivotal")

    def test_parse_query_terms(self):
        terms = parse_query_terms('"crucial role" emphasize underscore')
        self.assertIn("crucial role", terms)
        self.assertIn("emphasize", terms)
        self.assertIn("underscore", terms)

    def test_pick_era_explicit(self):
        self.assertEqual(pick_era("gpt4o"), "gpt4o")

    def test_pick_era_random_reproducible(self):
        self.assertEqual(pick_era(None, seed=42), pick_era(None, seed=42))

    def test_resolve_freeform(self):
        query, era = resolve_search_params(
            query='"crucial role" emphasize underscore', phrase=None,
            narrow=[], era="gpt4o", seed=None,
        )
        self.assertEqual(era, "gpt4o")
        self.assertIn("crucial role", query)

    def test_resolve_era_builder_random(self):
        query, era = resolve_search_params(
            query=None, phrase="crucial role",
            narrow=["underscore"], era=None, seed=1,
        )
        self.assertIn(era, ("gpt4", "gpt4o", "gpt5"))
        self.assertEqual(query, '"crucial role" underscore')

    def test_resolve_freeform_requires_era(self):
        with self.assertRaises(ValueError):
            resolve_search_params(
                query='"crucial role"', phrase=None,
                narrow=[], era=None, seed=None,
            )

    def test_eligible_narrowers_excludes_phrase_words(self):
        narrowers = eligible_narrowers("crucial role", ["crucial", "underscore", "emphasizing"])
        self.assertEqual(narrowers, ["underscore", "emphasizing"])

    def test_pick_random_search_phrase_mode(self):
        query, era, phrase, terms = pick_random_search(self.vocab, seed=0)
        self.assertIn(era, ("gpt4", "gpt4o", "gpt5"))
        self.assertIsNotNone(phrase)
        self.assertEqual(len(terms), 2)
        self.assertTrue(query.startswith('"'))

    def test_pick_random_search_vocab_mode(self):
        query, era, phrase, terms = pick_random_search(self.vocab, seed=2)
        self.assertIn(era, ("gpt4", "gpt4o", "gpt5"))
        self.assertIsNone(phrase)
        self.assertEqual(len(terms), 3)
        self.assertNotIn('"', query)
        self.assertEqual(query, build_vocab_query(terms))

    def test_pick_random_search_reproducible(self):
        a = pick_random_search(self.vocab, seed=42)
        b = pick_random_search(self.vocab, seed=42)
        self.assertEqual(a, b)

    def test_resolve_random_phrase_mode(self):
        query, era = resolve_search_params(
            query=None, phrase=None,
            narrow=[], era=None, seed=0,
            vocab_data=self.vocab,
        )
        self.assertIn(era, ("gpt4", "gpt4o", "gpt5"))
        self.assertTrue(query.startswith('"'))

    def test_resolve_random_vocab_mode(self):
        query, era = resolve_search_params(
            query=None, phrase=None,
            narrow=[], era=None, seed=2,
            vocab_data=self.vocab,
        )
        self.assertIn(era, ("gpt4", "gpt4o", "gpt5"))
        self.assertNotIn('"', query)
        self.assertEqual(len(query.split()), 3)

    def test_resolve_random_rejects_era_without_phrase(self):
        with self.assertRaises(ValueError):
            resolve_search_params(
                query=None, phrase=None,
                narrow=[], era="gpt4o", seed=None,
                vocab_data=self.vocab,
            )

    def test_resolve_random_rejects_narrow_without_phrase(self):
        with self.assertRaises(ValueError):
            resolve_search_params(
                query=None, phrase=None,
                narrow=["underscore"], era=None, seed=None,
                vocab_data=self.vocab,
            )


class TestSnippetEnrichment(unittest.TestCase):
    def setUp(self):
        from ai_detector import load_vocab
        self.vocab = load_vocab()
        self.era = "gpt4o"
        self.era_config = self.vocab["eras"][self.era]
        self.weights = self.vocab["weights"]

    def test_strip_html(self):
        self.assertEqual(
            strip_html('The <span class="searchmatch">crucial</span> role'),
            "The crucial role",
        )
        self.assertEqual(strip_html("world&#039;s"), "world's")
        self.assertEqual(
            strip_html("&quot;crucial role&quot;"),
            '"crucial role"',
        )

    def test_section_header_hit(self):
        hit = section_header_hit(
            "Challenges and Future Directions",
            self.era_config,
        )
        self.assertIn("Challenges", hit)

    def test_foster_false_positive(self):
        self.assertTrue(foster_false_positive("Robert Foster", "foster family"))
        self.assertFalse(foster_false_positive("Albert Einstein", "underscore"))

    def test_enrich_result_extra_indicators(self):
        hit = {
            "title": "Test Article",
            "pageid": 123,
            "snippet": 'played a <span class="searchmatch">crucial role</span> '
                       'while <span class="searchmatch">emphasizing</span> '
                       'the <span class="searchmatch">underscore</span> of legacy',
            "sectiontitle": "",
            "wordcount": 5000,
            "score": 12.5,
        }
        query = '"crucial role" emphasize'
        row = enrich_result(
            hit, query, self.era, self.era_config, self.weights, self.vocab,
        )
        self.assertEqual(row["prioritize"], "yes")
        self.assertIn("underscore", row["extra_indicators"])

    def test_enrich_result_prioritize_no_for_foster(self):
        hit = {
            "title": "Foster family",
            "pageid": 1,
            "snippet": "foster care history",
            "sectiontitle": "",
            "wordcount": 1000,
            "score": 1.0,
        }
        row = enrich_result(
            hit, "foster", self.era, self.era_config, self.weights, self.vocab,
        )
        self.assertEqual(row["prioritize"], "no")

    def test_is_ai_generated_template_name(self):
        self.assertTrue(is_ai_generated_template_name("AI-generated"))
        self.assertFalse(is_ai_generated_template_name("Citation needed"))

    def test_page_has_ai_generated_template(self):
        self.assertTrue(page_has_ai_generated_template(["Template:AI-generated", "Short description"]))
        self.assertFalse(page_has_ai_generated_template(["Short description"]))

    def test_lead_wikitext_detects_ai_tag(self):
        lead = (
            "{{Short description|None}}\n"
            "{{AI-generated|date=August 2025}}\n"
            "{{Use dmy dates|date=April 2021}}\n"
            "Article prose here."
        )
        self.assertTrue(has_ai_generated_template(lead))

    def test_normalize_pageid(self):
        self.assertEqual(normalize_pageid(74541498), 74541498)
        self.assertEqual(normalize_pageid("74541498"), 74541498)
        self.assertIsNone(normalize_pageid(None))

    def test_enrich_result_ai_tagged_deprioritizes(self):
        hit = {
            "title": "Tagged Article",
            "pageid": 42,
            "snippet": "played a crucial role emphasizing legacy",
            "sectiontitle": "",
            "wordcount": 5000,
            "score": 12.5,
        }
        row = enrich_result(
            hit, '"crucial role" emphasize', self.era, self.era_config,
            self.weights, self.vocab, ai_tagged=True,
        )
        self.assertEqual(row["ai_tagged"], "yes")
        self.assertEqual(row["prioritize"], "no")


class TestCsvOutput(unittest.TestCase):
    def test_csv_has_header(self):
        csv_text = format_triage_csv([{
            "title": "Test",
            "pageid": 1,
            "url": "https://en.wikipedia.org/wiki/Test",
            "era": "gpt4o",
            "query": '"crucial role"',
            "score": 1.0,
            "wordcount": 100,
            "section": "",
            "snippet": "text",
            "query_terms": "crucial role",
            "extra_indicators": "",
            "section_header_hit": "",
            "prioritize": "maybe",
            "ai_tagged": "no",
        }])
        self.assertTrue(csv_text.startswith("title,"))
        self.assertEqual(len(TRIAGE_COLUMNS), 12)

    def test_triage_csv_sorted_by_prioritize(self):
        csv_text = format_triage_csv([
            {
                "title": "No",
                "pageid": 1,
                "url": "https://en.wikipedia.org/wiki/No",
                "era": "gpt4o",
                "query": "q",
                "score": 99,
                "wordcount": 100,
                "section": "",
                "snippet": "text",
                "query_terms": "",
                "extra_indicators": "",
                "section_header_hit": "",
                "prioritize": "no",
                "ai_tagged": "no",
            },
            {
                "title": "Yes",
                "pageid": 2,
                "url": "https://en.wikipedia.org/wiki/Yes",
                "era": "gpt4o",
                "query": "q",
                "score": 1,
                "wordcount": 100,
                "section": "",
                "snippet": "text",
                "query_terms": "",
                "extra_indicators": "",
                "section_header_hit": "",
                "prioritize": "yes",
                "ai_tagged": "no",
            },
            {
                "title": "Maybe",
                "pageid": 3,
                "url": "https://en.wikipedia.org/wiki/Maybe",
                "era": "gpt4o",
                "query": "q",
                "score": 50,
                "wordcount": 100,
                "section": "",
                "snippet": "text",
                "query_terms": "",
                "extra_indicators": "",
                "section_header_hit": "",
                "prioritize": "maybe",
                "ai_tagged": "no",
            },
        ])
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual([r["title"] for r in rows], ["Yes", "Maybe", "No"])


if __name__ == "__main__":
    unittest.main()
