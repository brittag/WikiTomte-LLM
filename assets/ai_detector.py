#!/usr/bin/env python3
"""
Batch scanner for LLM-indicator patterns in Wikipedia articles.

Reads article titles from an input file, fetches prose via the Action API,
matches era-based vocabulary and phrases, clusters hits into passages, and
emits a JSON report.

Usage:
    python3 ai_detector.py articles.txt --era gpt4o -o report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import mwparserfromhell
except ImportError:
    print("mwparserfromhell not installed. Install: pip install mwparserfromhell", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("requests not installed. Install: pip install requests", file=sys.stderr)
    sys.exit(1)

log = logging.getLogger("ai_detector")

DEFAULT_USER_AGENT = (
    "AICleanupBot/0.1 (Britta Gustafson, brittag@gmail.com) "
    "AICleanup/0.1"
)

VOCAB_PATH = Path(__file__).resolve().parent / "ai_vocab.json"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
PASSAGE_CONTEXT_CHARS = 200
PASSAGE_CLUSTER_GAP = 400

# "key" from gpt4 vocab is too generic for word-boundary matching alone;
# exclude unless part of a phrase.
SKIP_STANDALONE_VOCAB = {"key"}


@dataclass
class Section:
    name: str
    level: int
    start: int
    text: str


@dataclass
class Match:
    indicator: str
    match_type: str
    offset: int
    weight: float
    section: str = ""


@dataclass
class Passage:
    section: str
    text: str
    char_start: int
    char_end: int
    score: float
    matches: List[Dict[str, Any]] = field(default_factory=list)


class WikimediaClient:
    """Rate-limited Wikipedia Action API client."""

    def __init__(self, user_agent: str, delay: float = 0.5):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.delay = delay
        self._last_request: float = 0.0

    def query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._rate_limit()
        merged = {"action": "query", "format": "json", "formatversion": "2", **params}
        resp = self.session.get(WIKIPEDIA_API, params=merged, timeout=30)
        if resp.status_code == 403:
            raise PermissionError(
                "403 Forbidden — check User-Agent. See Wikimedia User-Agent policy."
            )
        resp.raise_for_status()
        return resp.json()

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()


def load_vocab(path: Path = VOCAB_PATH) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_article_list(path: Path) -> List[str]:
    titles: List[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            titles.append(line)
    return titles


def fetch_page_data(client: WikimediaClient, title: str) -> Dict[str, Any]:
    """Fetch page metadata, wikitext, and categories."""
    data = client.query({
        "titles": title,
        "prop": "revisions|categories|info",
        "rvprop": "content",
        "rvslots": "main",
        "cllimit": "max",
        "inprop": "url",
    })
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        raise ValueError(f"Page not found: {title}")
    page = pages[0]
    if page.get("missing"):
        raise ValueError(f"Page not found: {title}")
    return page


def _strip_wikitext_chunk(chunk: str) -> str:
    """Remove templates, refs, and category links; return plain prose."""
    parsed = mwparserfromhell.parse(chunk)

    while True:
        templates = list(parsed.filter_templates())
        if not templates:
            break
        parsed.remove(templates[0])

    while True:
        refs = [
            tag for tag in parsed.filter_tags()
            if tag.tag in ("ref", "references")
        ]
        if not refs:
            break
        parsed.remove(refs[0])

    while True:
        to_remove = [
            wl for wl in parsed.filter_wikilinks()
            if str(wl.title).strip().lower().startswith(("category:", "file:", "image:"))
        ]
        if not to_remove:
            break
        parsed.remove(to_remove[0])

    text = parsed.strip_code(normalize=True, collapse=True)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text.strip()


def wikitext_to_sections(wikitext: str) -> Tuple[str, List[Section]]:
    """
    Strip templates/refs from wikitext and split into sections with offsets.
    Returns full plain text and a list of Section objects.
    """
    wikitext = re.sub(r"<!--.*?-->", "", wikitext, flags=re.DOTALL)

    lines = wikitext.split("\n")
    sections: List[Section] = []
    current_name = "Lead"
    current_level = 2
    current_lines: List[str] = []
    offset = 0
    full_parts: List[str] = []

    header_re = re.compile(r"^(=+)\s*(.+?)\s*\1$")

    def flush_section() -> None:
        nonlocal offset
        chunk = "\n".join(current_lines)
        text = _strip_wikitext_chunk(chunk) if chunk.strip() else ""
        if text:
            sections.append(Section(
                name=current_name,
                level=current_level,
                start=offset,
                text=text,
            ))
            full_parts.append(text)
            offset += len(text) + 1

    for line in lines:
        m = header_re.match(line.strip())
        if m:
            flush_section()
            current_level = len(m.group(1))
            current_name = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    flush_section()
    full_text = "\n".join(full_parts)
    return full_text, sections


def _word_boundary_pattern(word: str) -> re.Pattern[str]:
    escaped = re.escape(word)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    parts = [re.escape(p) for p in phrase.split()]
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.IGNORECASE)


def find_matches(
    full_text: str,
    sections: List[Section],
    era_config: Dict[str, Any],
    weights: Dict[str, float],
) -> List[Match]:
    """Scan text for era indicators and return weighted Match objects."""
    matches: List[Match] = []

    def section_for_offset(offset: int) -> str:
        chosen = "Lead"
        for sec in sections:
            if sec.start <= offset:
                chosen = sec.name
            else:
                break
        return chosen

    for phrase in era_config.get("phrases", []):
        pattern = _phrase_pattern(phrase)
        for m in pattern.finditer(full_text):
            matches.append(Match(
                indicator=phrase,
                match_type="phrase",
                offset=m.start(),
                weight=weights["phrase"],
                section=section_for_offset(m.start()),
            ))

    for word in era_config.get("vocab", []):
        if word.lower() in SKIP_STANDALONE_VOCAB:
            continue
        pattern = _word_boundary_pattern(word)
        for m in pattern.finditer(full_text):
            matches.append(Match(
                indicator=word,
                match_type="vocab",
                offset=m.start(),
                weight=weights["vocab"],
                section=section_for_offset(m.start()),
            ))

    for word in era_config.get("sentence_initial", []):
        pattern = re.compile(rf"(?:^|(?<=[.!?]\s))\s*{re.escape(word)}\s*,", re.IGNORECASE)
        for m in pattern.finditer(full_text):
            matches.append(Match(
                indicator=f"{word},",
                match_type="sentence_initial",
                offset=m.start(),
                weight=weights["sentence_initial"],
                section=section_for_offset(m.start()),
            ))

    for header_phrase in era_config.get("section_headers", []):
        header_lower = header_phrase.lower()
        for sec in sections:
            if header_lower in sec.name.lower():
                matches.append(Match(
                    indicator=header_phrase,
                    match_type="section_header",
                    offset=sec.start,
                    weight=weights["section_header"],
                    section=sec.name,
                ))

    matches.sort(key=lambda m: m.offset)
    return matches


def compute_suspicion_score(
    matches: List[Match],
    text_length: int,
    weights: Dict[str, float],
) -> float:
    if not matches or text_length == 0:
        return 0.0

    base = sum(m.weight for m in matches)
    distinct_types = len({m.match_type for m in matches})
    distinct_indicators = len({m.indicator.lower() for m in matches})
    cooccurrence = max(0, distinct_indicators - 1) * weights["cooccurrence_bonus"]

    # Normalize: ~3 weighted hits per 1000 chars approaches 1.0
    raw = (base + cooccurrence) / max(text_length / 1000.0, 0.5)
    return min(1.0, round(raw / 6.0, 4))


def cluster_passages(
    full_text: str,
    matches: List[Match],
    weights: Dict[str, float],
) -> List[Passage]:
    """Group nearby matches into passages with surrounding context."""
    if not matches:
        return []

    clusters: List[List[Match]] = []
    current_cluster: List[Match] = [matches[0]]

    for m in matches[1:]:
        prev = current_cluster[-1]
        same_section = m.section == prev.section
        nearby = (m.offset - prev.offset) <= PASSAGE_CLUSTER_GAP
        if same_section and nearby:
            current_cluster.append(m)
        else:
            clusters.append(current_cluster)
            current_cluster = [m]
    clusters.append(current_cluster)

    passages: List[Passage] = []
    for cluster in clusters:
        offsets = [m.offset for m in cluster]
        char_start = max(0, min(offsets) - PASSAGE_CONTEXT_CHARS)
        char_end = min(len(full_text), max(offsets) + PASSAGE_CONTEXT_CHARS)
        passage_text = full_text[char_start:char_end].strip()

        distinct = len({m.indicator.lower() for m in cluster})
        passage_score = min(1.0, sum(m.weight for m in cluster) / max(distinct, 1) / 5.0)

        passages.append(Passage(
            section=cluster[0].section,
            text=passage_text,
            char_start=char_start,
            char_end=char_end,
            score=round(passage_score, 4),
            matches=[
                {
                    "indicator": m.indicator,
                    "type": m.match_type,
                    "offset": m.offset,
                }
                for m in cluster
            ],
        ))

    passages.sort(key=lambda p: p.score, reverse=True)
    return passages


def detect_cautions(title: str, categories: List[str], vocab_data: Dict[str, Any]) -> List[str]:
    cautions: List[str] = []
    haystack = (title + " " + " ".join(categories)).lower()
    caution_kw = vocab_data.get("caution_keywords", {})
    caution_msgs = vocab_data.get("caution_messages", {})

    for category, keywords in caution_kw.items():
        if any(kw.lower() in haystack for kw in keywords):
            msg = caution_msgs.get(category)
            if msg and msg not in cautions:
                cautions.append(msg)
    return cautions


def scan_article(
    client: WikimediaClient,
    title: str,
    era: str,
    vocab_data: Dict[str, Any],
    min_score: float,
) -> Dict[str, Any]:
    """Scan a single article and return a result dict."""
    era_config = vocab_data["eras"][era]
    weights = vocab_data["weights"]

    page = fetch_page_data(client, title)
    pageid = page["pageid"]
    url = page.get("canonicalurl", f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}")

    revisions = page.get("revisions", [])
    if not revisions:
        raise ValueError(f"No revision content for: {title}")

    slot = revisions[0].get("slots", {}).get("main", {})
    wikitext = slot.get("content", "")
    if not wikitext:
        raise ValueError(f"Empty wikitext for: {title}")

    categories = [
        c.get("title", "").replace("Category:", "")
        for c in page.get("categories", [])
    ]

    full_text, sections = wikitext_to_sections(wikitext)
    matches = find_matches(full_text, sections, era_config, weights)
    suspicion_score = compute_suspicion_score(matches, len(full_text), weights)
    passages = cluster_passages(full_text, matches, weights)
    cautions = detect_cautions(title, categories, vocab_data)

    return {
        "title": page.get("title", title),
        "pageid": pageid,
        "url": url,
        "era": era,
        "era_label": era_config.get("label", era),
        "flagged": suspicion_score >= min_score and len(matches) >= 2,
        "suspicion_score": suspicion_score,
        "match_count": len(matches),
        "text_length": len(full_text),
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
        "all_matches": [
            {
                "indicator": m.indicator,
                "type": m.match_type,
                "offset": m.offset,
                "section": m.section,
                "weight": m.weight,
            }
            for m in matches
        ],
        "cautions": cautions,
    }


def run_batch(
    input_path: Path,
    era: str,
    output_path: Optional[Path],
    min_score: float,
    user_agent: str,
    delay: float,
) -> Dict[str, Any]:
    vocab_data = load_vocab()
    if era not in vocab_data["eras"]:
        valid = ", ".join(vocab_data["eras"].keys())
        raise ValueError(f"Unknown era '{era}'. Valid eras: {valid}")

    titles = read_article_list(input_path)
    if not titles:
        raise ValueError(f"No article titles found in {input_path}")

    client = WikimediaClient(user_agent=user_agent, delay=delay)
    articles: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for title in titles:
        log.info("Scanning: %s", title)
        try:
            result = scan_article(client, title, era, vocab_data, min_score)
            articles.append(result)
        except Exception as exc:
            log.warning("Failed to scan %s: %s", title, exc)
            errors.append({"title": title, "error": str(exc)})

    flagged = sum(1 for a in articles if a.get("flagged"))
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "input_file": str(input_path),
        "era": era,
        "era_label": vocab_data["eras"][era].get("label", era),
        "min_score": min_score,
        "summary": {
            "total": len(titles),
            "scanned": len(articles),
            "flagged": flagged,
            "errors": len(errors),
        },
        "articles": articles,
        "errors": errors,
    }

    output_json = json.dumps(report, indent=2, ensure_ascii=False)
    if output_path:
        output_path.write_text(output_json + "\n", encoding="utf-8")
        log.info("Wrote report to %s", output_path)
    else:
        print(output_json)

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan Wikipedia articles for LLM-indicator patterns.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s articles.txt --era gpt4o -o report.json
  %(prog)s articles.txt --era gpt4 --min-score 0.5
  %(prog)s articles.txt --era grok --delay 1.0 -o grok-report.json

Eras: gpt4, gpt4o, gpt5, grok
        """.strip(),
    )
    parser.add_argument(
        "input_file",
        help="Path to a text file with one article title per line (# for comments)",
    )
    parser.add_argument(
        "--era",
        required=True,
        choices=["gpt4", "gpt4o", "gpt5", "grok"],
        help="LLM era band to scan for (do not combine eras)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Write JSON report to this file (default: stdout)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.4,
        help="Flag articles at or above this suspicion score (default: 0.4)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between API requests (default: 0.5)",
    )
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("WIKIMEDIA_USER_AGENT", DEFAULT_USER_AGENT),
        help="User-Agent header for Wikimedia API requests",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main() -> None:
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    input_path = Path(args.input_file)
    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else None

    try:
        run_batch(
            input_path=input_path,
            era=args.era,
            output_path=output_path,
            min_score=args.min_score,
            user_agent=args.user_agent,
            delay=args.delay,
        )
    except (ValueError, PermissionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
