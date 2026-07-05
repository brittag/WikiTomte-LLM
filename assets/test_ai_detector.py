#!/usr/bin/env python3
"""Unit tests for ai_detector matching, scoring, and clustering (no network)."""

import json
import sys
import unittest
import csv
import io
from pathlib import Path

# Allow importing from assets/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_detector import (
    AI_GENERATED_CAUTION,
    Section,
    _articles_for_csv,
    cluster_passages,
    compute_suspicion_score,
    detect_cautions,
    find_matches,
    format_report_csv,
    has_ai_generated_template,
    is_ai_generated_template_name,
    is_title_case_heading,
    load_vocab,
    page_has_ai_generated_category,
    page_is_ai_tagged,
    prepare_article,
    read_article_list,
    resolve_eras,
    wikitext_to_sections,
)


SAMPLE_WIKITEXT = """{{Infobox person|name=Test Subject}}
'''Test Subject''' is a notable figure.

The subject played a [[crucial role]] in the landscape of modern science,
emphasizing the enduring interplay between theory and practice.
Additionally, the work serves as a testament to meticulous research.

== Legacy ==
The legacy continues to underscore the pivotal contributions made.

== Challenges and Future Directions ==
Researchers continue to delve into open questions.

[[Category:Test articles]]
"""

SAMPLE_PROSE = (
    "Test Subject is a notable figure. "
    "The subject played a crucial role in the landscape of modern science, "
    "emphasizing the enduring interplay between theory and practice. "
    "Additionally, the work serves as a testament to meticulous research. "
    "The legacy continues to underscore the pivotal contributions made. "
    "Researchers continue to delve into open questions."
)


class TestVocabConfig(unittest.TestCase):
    def test_load_vocab_has_all_eras(self):
        vocab = load_vocab()
        for era in ("gpt4", "gpt4o", "gpt5", "grok", "generic"):
            self.assertIn(era, vocab["eras"])
            self.assertIn("vocab", vocab["eras"][era])
            self.assertIn("phrases", vocab["eras"][era])

    def test_weights_present(self):
        vocab = load_vocab()
        for key in ("phrase", "vocab", "section_header", "title_case_heading", "sentence_initial", "punctuation"):
            self.assertIn(key, vocab["weights"])

    def test_resolve_eras_default_all(self):
        vocab = load_vocab()
        eras = resolve_eras(vocab, None)
        self.assertEqual(eras, list(vocab["eras"].keys()))

    def test_resolve_eras_single(self):
        vocab = load_vocab()
        self.assertEqual(resolve_eras(vocab, "grok"), ["grok"])
        self.assertEqual(resolve_eras(vocab, "generic"), ["generic"])

    def test_generic_era_has_cross_era_phrases(self):
        vocab = load_vocab()
        generic = vocab["eras"]["generic"]
        phrases = set(generic["phrases"])
        vocab = set(generic["vocab"])
        for expected in (
            "serves as",
            "independent coverage",
            "valuable insights",
            "in the heart of",
            "at the heart of",
            "in essence",
            "despite these challenges",
        ):
            self.assertIn(expected, phrases)
        for expected in ("delve", "tapestry", "quintessential", "synergy"):
            self.assertIn(expected, vocab)


class TestAiGeneratedTemplate(unittest.TestCase):
    def test_is_ai_generated_template_name(self):
        self.assertTrue(is_ai_generated_template_name("AI-generated"))
        self.assertTrue(is_ai_generated_template_name("Template:AI-generated"))
        self.assertTrue(is_ai_generated_template_name("subst:AI-generated"))
        self.assertTrue(is_ai_generated_template_name("ai_generated"))
        self.assertFalse(is_ai_generated_template_name("Infobox person"))

    def test_has_ai_generated_template_date_only(self):
        self.assertTrue(has_ai_generated_template("{{AI-generated|date=October 2025}}"))

    def test_page_has_ai_generated_category_feudalism(self):
        cat = "Articles containing suspected AI-generated texts from October 2025"
        self.assertTrue(page_has_ai_generated_category([cat]))
        self.assertTrue(page_has_ai_generated_category([f"Category:{cat}"]))

    def test_page_is_ai_tagged_from_category_only(self):
        cat = "Articles containing suspected AI-generated texts from October 2025"
        self.assertTrue(page_is_ai_tagged([], [cat]))

    def test_page_is_ai_tagged_from_template_api_title(self):
        self.assertTrue(page_is_ai_tagged(["Template:AI-generated"], []))

    def test_has_ai_generated_template_with_reason(self):
        wikitext = (
            "Some article text.\n"
            "{{AI-generated|date=January 2025|reason=LLM content}}\n"
            "More text."
        )
        self.assertTrue(has_ai_generated_template(wikitext))

    def test_has_ai_generated_template_subst_prefix(self):
        self.assertTrue(has_ai_generated_template("{{subst:AI-generated|date=January 2025}}"))

    def test_has_ai_generated_template_bare(self):
        self.assertTrue(has_ai_generated_template("{{AI-generated}}"))

    def test_has_ai_generated_template_absent(self):
        self.assertFalse(has_ai_generated_template(SAMPLE_WIKITEXT))

    def test_prepare_article_flags_ai_tagged(self):
        vocab = load_vocab()
        page = {
            "pageid": 99,
            "title": "Tagged Article",
            "canonicalurl": "https://en.wikipedia.org/wiki/Tagged_Article",
            "revisions": [{
                "slots": {
                    "main": {
                        "content": (
                            "Lead text.\n"
                            "{{AI-generated|date=January 2025|reason=test}}\n"
                        ),
                    },
                },
            }],
            "categories": [],
        }
        prepared = prepare_article(page, "Tagged Article", vocab)
        self.assertTrue(prepared.ai_tagged)
        self.assertIn(AI_GENERATED_CAUTION, prepared.cautions)


class TestWikitextParsing(unittest.TestCase):
    def test_strips_templates_and_categories(self):
        full_text, sections = wikitext_to_sections(SAMPLE_WIKITEXT)
        self.assertNotIn("{{Infobox", full_text)
        self.assertNotIn("Category:", full_text)
        self.assertIn("crucial role", full_text)

    def test_extracts_sections(self):
        _, sections = wikitext_to_sections(SAMPLE_WIKITEXT)
        names = [s.name for s in sections]
        self.assertIn("Lead", names)
        self.assertIn("Legacy", names)
        self.assertIn("Challenges and Future Directions", names)


class TestTitleCaseHeading(unittest.TestCase):
    def test_is_title_case_heading_positive(self):
        self.assertTrue(is_title_case_heading("Early Life"))
        self.assertTrue(is_title_case_heading("Career Highlights"))
        self.assertTrue(is_title_case_heading("Challenges and Future Directions"))

    def test_is_title_case_heading_negative(self):
        self.assertFalse(is_title_case_heading("Lead"))
        self.assertFalse(is_title_case_heading("Legacy"))
        self.assertFalse(is_title_case_heading("Early life"))
        self.assertFalse(is_title_case_heading("Career highlights"))
        self.assertFalse(is_title_case_heading("Challenges and future directions"))

    def test_find_matches_emits_title_case_heading(self):
        wikitext = (
            "Lead prose here.\n\n"
            "== Early Life ==\n"
            "Section text with landscape and pivotal words.\n"
        )
        _, sections = wikitext_to_sections(wikitext)
        full_text = " ".join(s.text for s in sections)
        vocab = load_vocab()
        era = vocab["eras"]["gpt4"]
        weights = vocab["weights"]
        matches = find_matches(full_text, sections, era, weights)
        title_case = [m for m in matches if m.match_type == "title_case_heading"]
        self.assertEqual(len(title_case), 1)
        self.assertEqual(title_case[0].indicator, "Early Life")
        self.assertEqual(title_case[0].weight, weights["title_case_heading"])

    def test_title_case_weight_lower_than_section_header(self):
        vocab = load_vocab()
        weights = vocab["weights"]
        self.assertLess(weights["title_case_heading"], weights["section_header"])

    def test_title_case_heading_increases_score(self):
        vocab = load_vocab()
        era = vocab["eras"]["gpt4"]
        weights = vocab["weights"]
        prose = "Some prose in the section."
        sections_title = [
            Section(name="Lead", level=2, start=0, text=prose),
            Section(name="Early Life", level=2, start=len(prose) + 1, text=prose),
        ]
        sections_sentence = [
            Section(name="Lead", level=2, start=0, text=prose),
            Section(name="Early life", level=2, start=len(prose) + 1, text=prose),
        ]
        full_text = prose + "\n" + prose
        with_title = find_matches(full_text, sections_title, era, weights)
        with_sentence = find_matches(full_text, sections_sentence, era, weights)
        score_title = compute_suspicion_score(with_title, len(full_text), weights)
        score_sentence = compute_suspicion_score(with_sentence, len(full_text), weights)
        self.assertGreater(score_title, score_sentence)


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.vocab = load_vocab()
        self.era = self.vocab["eras"]["gpt4"]
        self.weights = self.vocab["weights"]
        _, self.sections = wikitext_to_sections(SAMPLE_WIKITEXT)

    def test_finds_phrases_and_vocab(self):
        matches = find_matches(SAMPLE_PROSE, self.sections, self.era, self.weights)
        indicators = {m.indicator.lower() for m in matches}
        self.assertIn("crucial role", indicators)
        self.assertIn("landscape", indicators)
        self.assertIn("underscore", indicators)
        self.assertIn("delve", indicators)

    def test_finds_section_header(self):
        matches = find_matches(SAMPLE_PROSE, self.sections, self.era, self.weights)
        header_matches = [m for m in matches if m.match_type == "section_header"]
        self.assertTrue(any("Challenges" in m.indicator for m in header_matches))

    def test_sentence_initial_additionally(self):
        matches = find_matches(SAMPLE_PROSE, self.sections, self.era, self.weights)
        initial = [m for m in matches if m.match_type == "sentence_initial"]
        self.assertTrue(any("Additionally" in m.indicator for m in initial))


class TestPunctuation(unittest.TestCase):
    def setUp(self):
        self.vocab = load_vocab()
        self.era = self.vocab["eras"]["generic"]
        self.weights = self.vocab["weights"]
        self.prose = (
            "The project—launched in 2024—played a crucial role in shaping policy. "
            "Another clause—with more detail—followed."
        )
        self.sections = [Section(name="Lead", level=2, start=0, text=self.prose)]

    def test_finds_em_dash_in_generic_era(self):
        matches = find_matches(self.prose, self.sections, self.era, self.weights)
        em_dashes = [m for m in matches if m.match_type == "punctuation"]
        self.assertEqual(len(em_dashes), 4)
        self.assertTrue(all(m.indicator == "em dash" for m in em_dashes))

    def test_em_dash_not_in_gpt4_era(self):
        era = self.vocab["eras"]["gpt4"]
        matches = find_matches(self.prose, self.sections, era, self.weights)
        self.assertEqual([m for m in matches if m.match_type == "punctuation"], [])


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.vocab = load_vocab()
        self.era = self.vocab["eras"]["gpt4"]
        self.weights = self.vocab["weights"]
        _, self.sections = wikitext_to_sections(SAMPLE_WIKITEXT)

    def test_score_increases_with_more_matches(self):
        matches = find_matches(SAMPLE_PROSE, self.sections, self.era, self.weights)
        score = compute_suspicion_score(matches, len(SAMPLE_PROSE), self.weights)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_empty_matches_score_zero(self):
        score = compute_suspicion_score([], 1000, self.weights)
        self.assertEqual(score, 0.0)


class TestClustering(unittest.TestCase):
    def setUp(self):
        self.vocab = load_vocab()
        self.era = self.vocab["eras"]["gpt4"]
        self.weights = self.vocab["weights"]
        _, self.sections = wikitext_to_sections(SAMPLE_WIKITEXT)
        self.matches = find_matches(SAMPLE_PROSE, self.sections, self.era, self.weights)

    def test_clusters_into_passages(self):
        passages = cluster_passages(SAMPLE_PROSE, self.matches, self.weights)
        self.assertGreater(len(passages), 0)
        for p in passages:
            self.assertIn("text", p.__dict__)
            self.assertGreater(len(p.matches), 0)
            self.assertGreaterEqual(p.score, 0.0)


class TestCautions(unittest.TestCase):
    def setUp(self):
        self.vocab = load_vocab()

    def test_tech_caution(self):
        cautions = detect_cautions(
            "Example Software",
            ["Video game developers", "Windows software"],
            self.vocab,
        )
        self.assertTrue(any("technology" in c.lower() for c in cautions))

    def test_no_caution_for_generic_title(self):
        cautions = detect_cautions("Albert Einstein", ["20th-century physicists"], self.vocab)
        self.assertEqual(cautions, [])


class TestInputFile(unittest.TestCase):
    def test_read_article_list_skips_comments_and_blanks(self):
        examples = Path(__file__).resolve().parent.parent / "examples" / "articles.txt"
        titles = read_article_list(examples)
        self.assertIn("Albert Einstein", titles)
        self.assertIn("Python (programming language)", titles)
        self.assertEqual(len(titles), 2)


class TestReportSchema(unittest.TestCase):
    """Validate expected JSON shape using fixture data (no API)."""

    def test_article_result_shape(self):
        vocab = load_vocab()
        era = "gpt4"
        era_config = vocab["eras"][era]
        weights = vocab["weights"]
        _, sections = wikitext_to_sections(SAMPLE_WIKITEXT)
        matches = find_matches(SAMPLE_PROSE, sections, era_config, weights)
        score = compute_suspicion_score(matches, len(SAMPLE_PROSE), weights)
        passages = cluster_passages(SAMPLE_PROSE, matches, weights)

        result = {
            "title": "Test Subject",
            "pageid": 1,
            "url": "https://en.wikipedia.org/wiki/Test_Subject",
            "era": era,
            "flagged": score >= 0.4 and len(matches) >= 2,
            "suspicion_score": score,
            "match_count": len(matches),
            "passages": [
                {
                    "section": p.section,
                    "text": p.text,
                    "char_start": p.char_start,
                    "char_end": p.char_end,
                    "score": p.score,
                    "matches": p.matches,
                }
                for p in passages
            ],
            "cautions": [],
        }

        # Round-trip JSON must succeed
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        self.assertIn("suspicion_score", parsed)
        self.assertIn("passages", parsed)
        self.assertGreater(parsed["match_count"], 0)


class TestCsvOutput(unittest.TestCase):
    def test_csv_has_header_and_passage_rows(self):
        vocab = load_vocab()
        era = "gpt4"
        era_config = vocab["eras"][era]
        weights = vocab["weights"]
        _, sections = wikitext_to_sections(SAMPLE_WIKITEXT)
        matches = find_matches(SAMPLE_PROSE, sections, era_config, weights)
        score = compute_suspicion_score(matches, len(SAMPLE_PROSE), weights)
        passages = cluster_passages(SAMPLE_PROSE, matches, weights)

        report = {
            "era": era,
            "articles": [{
                "title": "Test Subject",
                "pageid": 1,
                "url": "https://en.wikipedia.org/wiki/Test_Subject",
                "era": era,
                "flagged": score >= 0.4 and len(matches) >= 2,
                "suspicion_score": score,
                "match_count": len(matches),
                "text_length": len(SAMPLE_PROSE),
                "passages": [
                    {
                        "section": p.section,
                        "text": p.text,
                        "char_start": p.char_start,
                        "char_end": p.char_end,
                        "score": p.score,
                        "matches": p.matches,
                    }
                    for p in passages
                ],
                "cautions": [],
            }],
            "errors": [],
        }

        csv_text = format_report_csv(report)
        lines = csv_text.strip().splitlines()
        self.assertTrue(lines[0].startswith("title,"))
        self.assertGreater(len(lines), 1)
        self.assertIn("Test Subject", csv_text)
        self.assertIn("crucial role", csv_text)

    def test_report_csv_sorted_by_suspicion_score(self):
        report = {
            "eras": ["gpt4"],
            "articles": [
                {
                    "title": "Low Score",
                    "pageid": 1,
                    "url": "https://en.wikipedia.org/wiki/Low",
                    "era": "gpt4",
                    "flagged": False,
                    "suspicion_score": 0.1,
                    "match_count": 1,
                    "text_length": 1000,
                    "passages": [{
                        "section": "Lead",
                        "text": "low",
                        "score": 0.1,
                        "matches": [],
                    }],
                    "cautions": [],
                },
                {
                    "title": "High Score",
                    "pageid": 2,
                    "url": "https://en.wikipedia.org/wiki/High",
                    "era": "gpt4",
                    "flagged": True,
                    "suspicion_score": 0.9,
                    "match_count": 5,
                    "text_length": 1000,
                    "passages": [{
                        "section": "Lead",
                        "text": "high",
                        "score": 0.9,
                        "matches": [],
                    }],
                    "cautions": [],
                },
            ],
            "errors": [],
        }
        rows = list(csv.DictReader(io.StringIO(format_report_csv(report))))
        titles = [r["title"] for r in rows if r["error"] == ""]
        self.assertEqual(titles[0], "High Score")
        self.assertEqual(titles[-1], "Low Score")


class TestMultiEraCsv(unittest.TestCase):
    def test_zero_hit_eras_collapsed_to_all(self):
        articles = [
            {
                "title": "Example",
                "pageid": 1,
                "url": "https://en.wikipedia.org/wiki/Example",
                "era": "gpt4",
                "flagged": False,
                "suspicion_score": 0.0,
                "match_count": 0,
                "text_length": 1000,
                "passages": [],
                "cautions": [],
            },
            {
                "title": "Example",
                "pageid": 1,
                "url": "https://en.wikipedia.org/wiki/Example",
                "era": "gpt4o",
                "flagged": False,
                "suspicion_score": 0.0,
                "match_count": 0,
                "text_length": 1000,
                "passages": [],
                "cautions": [],
            },
        ]
        collapsed = _articles_for_csv(articles)
        self.assertEqual(len(collapsed), 1)
        self.assertEqual(collapsed[0]["era"], "all")

    def test_only_eras_with_hits_in_csv(self):
        articles = [
            {
                "title": "Example",
                "pageid": 1,
                "url": "https://en.wikipedia.org/wiki/Example",
                "era": "gpt4",
                "flagged": True,
                "suspicion_score": 0.8,
                "match_count": 3,
                "text_length": 1000,
                "passages": [{
                    "section": "Lead",
                    "text": "crucial role text",
                    "score": 0.5,
                    "matches": [{"indicator": "crucial role", "type": "phrase"}],
                }],
                "cautions": [],
            },
            {
                "title": "Example",
                "pageid": 1,
                "url": "https://en.wikipedia.org/wiki/Example",
                "era": "gpt4o",
                "flagged": False,
                "suspicion_score": 0.0,
                "match_count": 0,
                "text_length": 1000,
                "passages": [],
                "cautions": [],
            },
        ]
        collapsed = _articles_for_csv(articles)
        self.assertEqual(len(collapsed), 1)
        self.assertEqual(collapsed[0]["era"], "gpt4")


if __name__ == "__main__":
    unittest.main()
