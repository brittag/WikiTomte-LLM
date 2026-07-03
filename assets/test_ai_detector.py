#!/usr/bin/env python3
"""Unit tests for ai_detector matching, scoring, and clustering (no network)."""

import json
import sys
import unittest
from pathlib import Path

# Allow importing from assets/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_detector import (
    cluster_passages,
    compute_suspicion_score,
    detect_cautions,
    find_matches,
    load_vocab,
    read_article_list,
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
        for era in ("gpt4", "gpt4o", "gpt5", "grok"):
            self.assertIn(era, vocab["eras"])
            self.assertIn("vocab", vocab["eras"][era])
            self.assertIn("phrases", vocab["eras"][era])

    def test_weights_present(self):
        vocab = load_vocab()
        for key in ("phrase", "vocab", "section_header", "sentence_initial"):
            self.assertIn(key, vocab["weights"])


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


if __name__ == "__main__":
    unittest.main()
