#!/usr/bin/env python3
"""
CirrusSearch triage tool — find candidate articles via Wikipedia search,
enrich snippets with era indicators, and export a reviewable CSV + articles.txt.

Usage:
    python3 search_triage.py -o triage.csv --write-articles candidates.txt
    python3 search_triage.py --phrase "crucial role" --narrow underscore emphasizing -o triage.csv
    python3 search_triage.py --query '"crucial role" emphasize underscore' --era gpt4o -o triage.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("requests not installed. Install: pip install requests", file=sys.stderr)
    sys.exit(1)

from ai_detector import (
    Section,
    find_matches,
    has_ai_generated_template,
    load_vocab,
    normalize_pageid,
)
from config import get_user_agent

log = logging.getLogger("search_triage")

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
ERA_POOL = ["gpt4", "gpt4o", "gpt5"]
SRPROP = "size|wordcount|timestamp|snippet|sectiontitle|sectionsnippet"

TRIAGE_COLUMNS = [
    "title",
    "url",
    "prioritize",
    "ai_tagged",
    "era",
    "query",
    "wordcount",
    "section",
    "snippet",
    "query_terms",
    "extra_indicators",
    "section_header_hit",
]

PRIORITIZE_ORDER = {"yes": 0, "maybe": 1, "no": 2}


class CirrusSearchClient:
    """Rate-limited CirrusSearch client via Action API."""

    def __init__(self, user_agent: str, delay: float = 0.5):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.delay = delay
        self._last_request: float = 0.0

    def search_page(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Return (results, has_more)."""
        self._rate_limit()
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srsearch": query,
            "srnamespace": 0,
            "srwhat": "text",
            "srlimit": min(limit, 500),
            "srprop": SRPROP,
        }
        if offset:
            params["sroffset"] = offset

        resp = self.session.get(WIKIPEDIA_API, params=params, timeout=30)
        if resp.status_code == 403:
            raise PermissionError(
                "403 Forbidden — check User-Agent in config.json. "
                "See Wikimedia User-Agent policy."
            )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("query", {}).get("search", [])
        has_more = "continue" in data and len(results) >= min(limit, 500)
        return results, has_more

    def search_all(self, query: str, max_results: int = 500) -> List[Dict[str, Any]]:
        """Paginate through search results up to max_results."""
        all_results: List[Dict[str, Any]] = []
        params: Dict[str, Any] = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srsearch": query,
            "srnamespace": 0,
            "srwhat": "text",
            "srlimit": min(max_results, 500),
            "srprop": SRPROP,
        }

        while len(all_results) < max_results:
            self._rate_limit()
            resp = self.session.get(WIKIPEDIA_API, params=params, timeout=30)
            if resp.status_code == 403:
                raise PermissionError(
                    "403 Forbidden — check User-Agent in config.json."
                )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            if not results:
                break
            remaining = max_results - len(all_results)
            all_results.extend(results[:remaining])
            if len(all_results) >= max_results or "continue" not in data:
                break
            params.update(data["continue"])
            self._last_request = time.monotonic()

        return all_results

    def fetch_lead_wikitext_by_pageids(
        self, pageids: List[Any], chunk_size: int = 50
    ) -> Dict[int, str]:
        """Batch-fetch lead-section wikitext (rvsection=0) per pageid."""
        result: Dict[int, str] = {}
        unique_ids = [
            pid for pid in (normalize_pageid(p) for p in pageids) if pid is not None
        ]
        unique_ids = list(dict.fromkeys(unique_ids))

        for i in range(0, len(unique_ids), chunk_size):
            chunk = unique_ids[i:i + chunk_size]
            self._rate_limit()
            params: Dict[str, Any] = {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "revisions",
                "pageids": "|".join(str(pid) for pid in chunk),
                "rvprop": "content",
                "rvslots": "main",
                "rvsection": "0",
            }
            resp = self.session.get(WIKIPEDIA_API, params=params, timeout=30)
            if resp.status_code == 403:
                raise PermissionError(
                    "403 Forbidden — check User-Agent in config.json."
                )
            resp.raise_for_status()
            data = resp.json()
            for page in data.get("query", {}).get("pages", []):
                pid = normalize_pageid(page.get("pageid"))
                if pid is None:
                    continue
                revisions = page.get("revisions", [])
                if not revisions:
                    continue
                slot = revisions[0].get("slots", {}).get("main", {})
                result[pid] = slot.get("content", "")

        return result

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()


def pick_era(era: Optional[str], seed: Optional[int] = None) -> str:
    if era:
        if era not in ERA_POOL:
            valid = ", ".join(ERA_POOL)
            raise ValueError(f"Unknown era '{era}'. Valid eras: {valid}")
        return era
    rng = random.Random(seed)
    return rng.choice(ERA_POOL)


def eligible_narrowers(phrase: str, vocab: List[str]) -> List[str]:
    """Vocab words not already contained in the target phrase."""
    lower_phrase = phrase.lower()
    return [w for w in vocab if w.lower() not in lower_phrase]


def _phrase_mode_available(era_config: Dict[str, Any]) -> bool:
    vocab = era_config.get("vocab", [])
    return any(
        len(eligible_narrowers(phrase, vocab)) >= 2
        for phrase in era_config.get("phrases", [])
    )


def _vocab_mode_available(era_config: Dict[str, Any]) -> bool:
    return len(era_config.get("vocab", [])) >= 3


def pick_random_search(
    vocab_data: Dict[str, Any],
    seed: Optional[int] = None,
) -> Tuple[str, str, Optional[str], List[str]]:
    """
    Pick era and search terms from ai_vocab.json.

    Randomly uses phrase mode (1 phrase + 2 narrowers) or vocab mode (3 words).
    Returns (query_string, era, phrase_or_none, terms).
    """
    rng = random.Random(seed)
    eligible_eras = [
        era for era in ERA_POOL
        if _phrase_mode_available(vocab_data["eras"][era])
        or _vocab_mode_available(vocab_data["eras"][era])
    ]
    if not eligible_eras:
        raise ValueError("No eras available for random search")

    era = rng.choice(eligible_eras)
    era_config = vocab_data["eras"][era]
    phrase_ok = _phrase_mode_available(era_config)
    vocab_ok = _vocab_mode_available(era_config)

    if phrase_ok and vocab_ok:
        use_vocab = rng.random() < 0.5
    else:
        use_vocab = vocab_ok

    if use_vocab:
        words = rng.sample(era_config["vocab"], 3)
        return build_vocab_query(words), era, None, words

    phrases_with_narrowers = [
        phrase for phrase in era_config.get("phrases", [])
        if len(eligible_narrowers(phrase, era_config.get("vocab", []))) >= 2
    ]
    phrase = rng.choice(phrases_with_narrowers)
    candidates = eligible_narrowers(phrase, era_config.get("vocab", []))
    narrow = rng.sample(candidates, 2)
    return build_query(phrase, narrow), era, phrase, narrow


def build_vocab_query(words: List[str]) -> str:
    """Build CirrusSearch query from unquoted vocab words."""
    parts = [w.strip() for w in words if w.strip()]
    if not parts:
        raise ValueError("At least one vocab word is required")
    return " ".join(parts)


def build_query(phrase: str, narrow: List[str]) -> str:
    """Build CirrusSearch query: quoted phrase + unquoted narrowers."""
    phrase = phrase.strip()
    if not phrase:
        raise ValueError("--phrase is required for era builder mode")
    if phrase.startswith('"') and phrase.endswith('"'):
        quoted = phrase
    else:
        quoted = f'"{phrase}"'
    parts = [quoted] + [w.strip() for w in narrow if w.strip()]
    return " ".join(parts)


def parse_query_terms(query: str) -> List[str]:
    """Extract searchable terms from a CirrusSearch query string."""
    terms: List[str] = []
    for match in re.finditer(r'"([^"]+)"', query):
        terms.append(match.group(1))
    remainder = re.sub(r'"[^"]+"', " ", query)
    remainder = re.sub(r"insource:[^\s]+", " ", remainder)
    for word in remainder.split():
        word = word.strip()
        if word and not word.startswith("-"):
            terms.append(word)
    return terms


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ").strip()


def section_header_hit(section_title: str, era_config: Dict[str, Any]) -> str:
    if not section_title:
        return ""
    lower = section_title.lower()
    for header in era_config.get("section_headers", []):
        if header.lower() in lower:
            return header
    return ""


def foster_false_positive(title: str, query: str) -> bool:
    """Title contains Foster when query used foster-related narrowing."""
    if "foster" not in query.lower():
        return False
    return "foster" in title.lower()


def enrich_result(
    hit: Dict[str, Any],
    query: str,
    era: str,
    era_config: Dict[str, Any],
    weights: Dict[str, float],
    vocab_data: Dict[str, Any],
    ai_tagged: bool = False,
) -> Dict[str, Any]:
    title = hit.get("title", "")
    url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"

    snippet_raw = hit.get("snippet", "") or hit.get("sectionsnippet", "")
    snippet = strip_html(snippet_raw)
    section = strip_html(hit.get("sectiontitle", "") or "")

    pseudo_section = [Section(name=section or "Lead", level=2, start=0, text=snippet)]
    matches = find_matches(snippet, pseudo_section, era_config, weights)

    query_terms_list = parse_query_terms(query)

    found_query_terms: List[str] = []
    found_extra: List[str] = []
    for m in matches:
        key = m.indicator.lower()
        in_query = any(
            key == qt.lower() or key in qt.lower() or qt.lower() in key
            for qt in query_terms_list
        )
        if in_query:
            if m.indicator not in found_query_terms:
                found_query_terms.append(m.indicator)
        else:
            if m.indicator not in found_extra:
                found_extra.append(m.indicator)

    header_hit = section_header_hit(section, era_config)

    if ai_tagged:
        prioritize = "no"
    elif foster_false_positive(title, query):
        prioritize = "no"
    elif found_extra or header_hit:
        prioritize = "yes"
    elif found_query_terms:
        prioritize = "maybe"
    else:
        prioritize = "maybe"

    return {
        "title": title,
        "url": url,
        "era": era,
        "query": query,
        "wordcount": hit.get("wordcount", ""),
        "section": section,
        "snippet": snippet,
        "query_terms": "; ".join(found_query_terms),
        "extra_indicators": "; ".join(found_extra),
        "section_header_hit": header_hit,
        "prioritize": prioritize,
        "ai_tagged": "yes" if ai_tagged else "no",
    }


def sort_triage_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort by prioritize (yes, maybe, no), then title."""
    return sorted(
        rows,
        key=lambda r: (
            PRIORITIZE_ORDER.get(r.get("prioritize", ""), 99),
            r.get("title", "").lower(),
        ),
    )


def format_triage_csv(rows: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TRIAGE_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in sort_triage_rows(rows):
        writer.writerow(row)
    return buf.getvalue()


def write_articles_file(path: Path, rows: List[Dict[str, Any]]) -> None:
    seen: set[str] = set()
    lines: List[str] = []
    for row in rows:
        title = row["title"]
        if title not in seen:
            seen.add(title)
            lines.append(title)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Wrote %d article titles to %s", len(lines), path)


def resolve_search_params(
    query: Optional[str],
    phrase: Optional[str],
    narrow: List[str],
    era: Optional[str],
    seed: Optional[int],
    *,
    vocab_data: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Return (query_string, era)."""
    if query:
        if not era:
            raise ValueError("--era is required when using --query (freeform mode)")
        if era not in ERA_POOL:
            valid = ", ".join(ERA_POOL)
            raise ValueError(f"Unknown era '{era}'. Valid eras: {valid}")
        return query, era

    if phrase:
        chosen_era = pick_era(era, seed=seed)
        if not era:
            log.info("Random era selected: %s", chosen_era)
        return build_query(phrase, narrow), chosen_era

    if era:
        raise ValueError("--era requires --query or --phrase")
    if narrow:
        raise ValueError("--narrow requires --phrase")
    if vocab_data is None:
        raise ValueError("vocab_data required for random search")
    query_str, chosen_era, chosen_phrase, chosen_terms = pick_random_search(
        vocab_data, seed=seed
    )
    if chosen_phrase:
        log.info(
            "Random search: era=%s mode=phrase phrase=%r narrowers=%s",
            chosen_era, chosen_phrase, chosen_terms,
        )
    else:
        log.info(
            "Random search: era=%s mode=vocab terms=%s",
            chosen_era, chosen_terms,
        )
    return query_str, chosen_era


def run_triage(
    query: Optional[str],
    phrase: Optional[str],
    narrow: List[str],
    era: Optional[str],
    seed: Optional[int],
    limit: int,
    output_path: Optional[Path],
    articles_path: Optional[Path],
    user_agent: str,
    delay: float,
) -> Dict[str, Any]:
    vocab_data = load_vocab()
    weights = vocab_data["weights"]

    query_str, chosen_era = resolve_search_params(
        query, phrase, narrow, era, seed,
        vocab_data=vocab_data,
    )
    era_config = vocab_data["eras"][chosen_era]

    log.info("Query: %s", query_str)
    log.info("Era: %s (%s)", chosen_era, era_config.get("label", chosen_era))

    client = CirrusSearchClient(user_agent=user_agent, delay=delay)
    hits = client.search_all(query_str, max_results=limit)

    pageids = [hit.get("pageid") for hit in hits if hit.get("pageid")]
    lead_by_page = client.fetch_lead_wikitext_by_pageids(pageids)

    rows = []
    for hit in hits:
        pid = normalize_pageid(hit.get("pageid"))
        lead = lead_by_page.get(pid, "") if pid is not None else ""
        rows.append(
            enrich_result(
                hit,
                query_str,
                chosen_era,
                era_config,
                weights,
                vocab_data,
                ai_tagged=has_ai_generated_template(lead),
            )
        )

    tagged_count = sum(1 for row in rows if row["ai_tagged"] == "yes")
    if tagged_count:
        log.info("%d already tagged with {{AI-generated}}", tagged_count)

    rows = sort_triage_rows(rows)

    prioritize_counts = {"yes": 0, "maybe": 0, "no": 0}
    for row in rows:
        prioritize_counts[row["prioritize"]] = prioritize_counts.get(row["prioritize"], 0) + 1

    warnings: List[str] = []
    if len(rows) < 10:
        warnings.append(f"Only {len(rows)} results — query may be too narrow")
    if len(rows) > 500:
        warnings.append(f"{len(rows)} results — query may be too broad")

    for w in warnings:
        log.warning(w)

    csv_content = format_triage_csv(rows)
    if output_path:
        output_path.write_text(csv_content, encoding="utf-8")
        log.info("Wrote triage CSV to %s", output_path)
    else:
        print(csv_content, end="")

    if articles_path:
        write_articles_file(articles_path, rows)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "query": query_str,
        "era": chosen_era,
        "total": len(rows),
        "already_tagged": tagged_count,
        "prioritize": prioritize_counts,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search Wikipedia for LLM-indicator patterns and triage results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -o triage.csv --write-articles candidates.txt
  %(prog)s --phrase "crucial role" --narrow underscore emphasizing -o triage.csv
  %(prog)s --query '"crucial role" emphasize underscore' --era gpt4o -o triage.csv
        """.strip(),
    )
    parser.add_argument("--query", help="Raw CirrusSearch query (requires --era)")
    parser.add_argument("--era", choices=ERA_POOL, help="Era band (random in era-builder if omitted)")
    parser.add_argument("--phrase", help="Target phrase for era builder (2-4 words)")
    parser.add_argument("--narrow", nargs="+", default=[], help="Narrowing vocab words for era builder")
    parser.add_argument("--seed", type=int, help="Seed for reproducible random search or era-builder era selection")
    parser.add_argument("--limit", type=int, default=100, help="Max search results (default: 100)")
    parser.add_argument("-o", "--output", help="Write triage CSV to this file")
    parser.add_argument("--write-articles", help="Write article titles to this file for ai_detector.py")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between API requests")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
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

    output_path = Path(args.output) if args.output else None
    articles_path = Path(args.write_articles) if args.write_articles else None

    try:
        summary = run_triage(
            query=args.query,
            phrase=args.phrase,
            narrow=args.narrow,
            era=args.era,
            seed=args.seed,
            limit=args.limit,
            output_path=output_path,
            articles_path=articles_path,
            user_agent=get_user_agent(),
            delay=args.delay,
        )
        log.info(
            "Done: %d results (prioritize: %d yes, %d maybe, %d no)",
            summary["total"],
            summary["prioritize"].get("yes", 0),
            summary["prioritize"].get("maybe", 0),
            summary["prioritize"].get("no", 0),
        )
    except (ValueError, PermissionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
