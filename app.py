#!/usr/bin/env python3
"""WikiTomte-LLM web UI — search and scan for LLM-indicator patterns."""

from __future__ import annotations

import base64
import html
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "assets"))

from ai_detector import format_report_csv, parse_article_titles, run_batch_from_titles
from config import get_user_agent
from search_triage import format_triage_csv, run_triage, titles_for_scan

DEFAULT_LIMIT = 50
DEFAULT_DELAY = 0.5
DEFAULT_MIN_SCORE = 0.4
DISPLAY_MIN_PASSAGE_SCORE = 0.3
TABLE_MAX_HEIGHT = 600

# LinkColumn display_text only supports static text or a URL regex — not another
# column. Extract the article name from the Wikipedia /wiki/ path for display.
ARTICLE_LINK_DISPLAY = r".*/wiki/([^#?&]+)"
TOMTE_IMAGE = Path(__file__).resolve().parent / "docs" / "jenny-nystrom-tomte.png"


def _article_link(url: str, title: str) -> str:
    return url or title


def _table_height(row_count: int) -> int:
    return min(35 * max(row_count, 1) + 38, TABLE_MAX_HEIGHT)


@st.cache_data
def _tomte_img_src() -> str:
    data = base64.b64encode(TOMTE_IMAGE.read_bytes()).decode()
    return f"data:image/png;base64,{data}"


def _group_triage_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"yes": [], "maybe": [], "no": []}
    for row in rows:
        bucket = row.get("prioritize", "no")
        if bucket not in groups:
            bucket = "no"
        groups[bucket].append(row)
    return groups


TRIAGE_LIST_CSS = """
<style>
.triage-block { margin: 0 0 0.75rem 0; }
.triage-block:last-child { margin-bottom: 0; }
.triage-heading {
    margin: 0 0 0.2rem 0;
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1.2;
}
.triage-note {
    margin: 0 0 0.35rem 0;
    font-size: 0.78rem;
    color: rgba(49, 51, 63, 0.65);
    line-height: 1.2;
}
.triage-list { margin: 0; padding: 0; list-style: none; }
.triage-item {
    margin: 0;
    padding: 0.12rem 0;
    font-size: 0.84rem;
    line-height: 1.25;
    border-bottom: 1px solid rgba(49, 51, 63, 0.08);
}
.triage-item:last-child { border-bottom: none; }
.t-meta { color: rgba(49, 51, 63, 0.62); }
.t-meta::before { content: " · "; }
.t-snippet::before { content: " — "; color: rgba(49, 51, 63, 0.45); }
.t-sig { color: rgba(49, 51, 63, 0.62); font-style: italic; }
.t-sig::before { content: " · "; }
</style>
"""


def _html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _score_pct(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{round(float(value) * 100)}%"


def _format_triage_item_html(row: dict[str, Any], bucket: str) -> str:
    title = _html_escape(row.get("title", ""))
    url = _html_escape(row.get("url", ""))
    section = _html_escape(row.get("section", ""))
    snippet = _html_escape(row.get("snippet", ""))

    parts = [f'<a href="{url}"><strong>{title}</strong></a>']
    if section:
        parts.append(f'<span class="t-meta">{section}</span>')
    if snippet:
        parts.append(f'<span class="t-snippet">{snippet}</span>')

    if bucket == "yes":
        signals: list[str] = []
        extra = row.get("extra_indicators", "")
        header = row.get("section_header_hit", "")
        if extra:
            signals.append(_html_escape(extra))
        if header:
            signals.append(_html_escape(header))
        if signals:
            parts.append(f'<span class="t-sig">+ {"; ".join(signals)}</span>')
    elif bucket == "maybe":
        query_terms = row.get("query_terms", "")
        if query_terms:
            parts.append(f'<span class="t-sig">{_html_escape(query_terms)}</span>')
    elif bucket == "no" and row.get("ai_tagged") == "yes":
        parts.append('<span class="t-sig">AI-tagged</span>')

    return f'<li class="triage-item">{"".join(parts)}</li>'


def _render_triage_list_html(
    heading: str,
    note: str,
    rows: list[dict[str, Any]],
    bucket: str,
) -> str:
    items = "".join(_format_triage_item_html(row, bucket) for row in rows)
    return (
        f'<div class="triage-block">'
        f'<p class="triage-heading">{_html_escape(heading)} ({len(rows)})</p>'
        f'<p class="triage-note">{_html_escape(note)}</p>'
        f'<ul class="triage-list">{items}</ul>'
        f"</div>"
    )


def _render_triage_results(rows: list[dict[str, Any]]) -> None:
    groups = _group_triage_rows(rows)
    blocks: list[str] = [TRIAGE_LIST_CSS]

    if groups["yes"]:
        blocks.append(
            _render_triage_list_html(
                "Worth opening",
                "Extra era indicators or suspicious section header in snippet.",
                groups["yes"],
                "yes",
            )
        )

    if groups["maybe"]:
        blocks.append(
            _render_triage_list_html(
                "Worth a skim",
                "Query-term matches only.",
                groups["maybe"],
                "maybe",
            )
        )

    if blocks:
        st.markdown("\n".join(blocks), unsafe_allow_html=True)

    if groups["no"]:
        with st.expander(f"Skipped as already tagged for AI cleanup ({len(groups['no'])})", expanded=False):
            skipped_items = "".join(
                _format_triage_item_html(row, "no") for row in groups["no"]
            )
            st.markdown(
                f'<ul class="triage-list">{skipped_items}</ul>',
                unsafe_allow_html=True,
            )


def _collapse_articles_for_display(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse zero-hit era rows; keep one summary row when no era matched."""
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for article in articles:
        groups.setdefault(article["title"], []).append(article)

    collapsed: list[dict[str, Any]] = []
    for era_articles in groups.values():
        with_hits = [article for article in era_articles if article.get("match_count", 0) > 0]
        if with_hits:
            collapsed.extend(with_hits)
        else:
            collapsed.append(dict(era_articles[0]))
    return collapsed


def _scan_report_to_display_dataframe(report: dict[str, Any]) -> pd.DataFrame:
    articles = _collapse_articles_for_display(report.get("articles", []))
    articles.sort(
        key=lambda article: (
            not article.get("flagged", False),
            -article.get("suspicion_score", 0),
            article.get("title", "").lower(),
        )
    )
    rows: list[dict[str, Any]] = []
    for article in articles:
        passages = [
            passage
            for passage in (article.get("passages") or [])
            if passage.get("score", 0) >= DISPLAY_MIN_PASSAGE_SCORE
        ]
        passages.sort(key=lambda passage: passage.get("score", 0), reverse=True)
        if not passages:
            continue

        base = {
            "article": _article_link(article["url"], article["title"]),
            "article score": _score_pct(article.get("suspicion_score", 0)),
            "ai tagged": "yes" if article.get("ai_tagged") else "no",
        }
        for passage in passages:
            indicators = "; ".join(
                match["indicator"] for match in passage.get("matches", [])
            )
            rows.append(
                {
                    **base,
                    "section": passage.get("section", ""),
                    "passage score": _score_pct(passage.get("score", 0)),
                    "passage": passage.get("text", ""),
                    "indicators": indicators,
                    "error": "",
                }
            )

    for err in report.get("errors", []):
        rows.append(
            {
                "article": err["title"],
                "article score": "",
                "ai tagged": "",
                "section": "",
                "passage score": "",
                "passage": "",
                "indicators": "",
                "error": err.get("error", ""),
            }
        )

    return pd.DataFrame(rows)


def _render_scan_table(df: pd.DataFrame) -> None:
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        height=_table_height(len(df)),
        column_order=[
            "article",
            "article score",
            "section",
            "passage score",
            "passage",
            "indicators",
            "ai tagged",
            "error",
        ],
        column_config={
            "article": st.column_config.LinkColumn(
                "Article", display_text=ARTICLE_LINK_DISPLAY,
                width="medium"
            ),
            "article score": st.column_config.TextColumn(
                "Article %", width="small"
            ),
            "section": st.column_config.TextColumn("Section", width="small"),
            "passage score": st.column_config.TextColumn(
                "Passage %", width="small"
            ),
            "passage": st.column_config.TextColumn("Passage", width="large"),
            "indicators": st.column_config.TextColumn("Indicators", width="medium"),
            "ai tagged": st.column_config.TextColumn("Already tagged for AI cleanup", width="medium"),
            "error": st.column_config.TextColumn("Error", width="medium"),
        },
    )


def _render_setup_error(exc: ValueError) -> None:
    st.error(str(exc))
    st.markdown(
        """
### Set up your Wikimedia User-Agent

Wikipedia requires a descriptive User-Agent with contact info.

**In GitHub Codespaces:**

1. Go to **GitHub → Settings → Codespaces → Secrets**
2. Add a secret named `WIKITOMTE_USER_AGENT`
3. Value example: `WikiTomte-LLM/1.0 (User:YourUsername, you@example.com) WikiTomte-LLM/1.0`
4. Rebuild or recreate your codespace

**Running locally:**

```bash
cp config.example.json config.json
# Edit config.json with your contact info
```

Or set the environment variable `WIKITOMTE_USER_AGENT`.

See the [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy).
        """
    )


def main() -> None:
    st.set_page_config(page_title="WikiTomte-LLM", layout="wide")
    st.markdown(
        f"""
<style>
.block-container {{
    padding-top: 1rem;
    position: relative;
}}
.wikitomte-tomte {{
    position: absolute;
    top: 0.75rem;
    right: 0;
    width: 200px;
    height: auto;
    pointer-events: none;
}}
h1#wiki-tomte-llm {{
    font-size: 2rem;
}}
[data-testid="stCaptionContainer"], [data-testid="stMarkdown"] {{
    background-color: white;
    width: fit-content;
    opacity: .9;
}}
hr {{
    margin: 0rem;
}}
div[data-testid="stHeading"] h2 {{
    margin-top: 0rem;
}}
div[data-testid="stExpander"] {{
    margin-top: 0.5rem;
}}
</style>
<img class="wikitomte-tomte" src="{_tomte_img_src()}" alt="">
        """,
        unsafe_allow_html=True,
    )
    st.title("WikiTomte-LLM")
    st.markdown(
        """
        Help with [WikiProject AI Cleanup](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_AI_Cleanup) by finding Wikipedia articles with potential undetected LLM-generated text.

        Read [the AI Cleanup Guide](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_AI_Cleanup/Guide) before tagging or taking action. This tool is based on [Gnomingstuff's guide](https://en.wikipedia.org/wiki/User:Gnomingstuff/Guide_to_finding_AI-generated_text), which includes a [quiz](https://en.wikipedia.org/wiki/User:Gnomingstuff/Guide_to_finding_AI-generated_text#Quiz:_Test_your_searching_skills!).
        """
    )

    try:
        user_agent = get_user_agent()
    except ValueError as exc:
        _render_setup_error(exc)
        return

    if "scan_titles_text" not in st.session_state:
        st.session_state.scan_titles_text = ""
    if "search_result" not in st.session_state:
        st.session_state.search_result = None
    if "scan_report" not in st.session_state:
        st.session_state.scan_report = None

    st.header("1. Search articles")
    st.markdown(
        ""
        "Search for random combos of [AI vocabulary](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing#Language_and_grammar) to make a list of articles with potential LLM-generated text "
        f"(up to {DEFAULT_LIMIT} results). "
    )

    run_search = st.button("Run search", type="primary")

    if run_search:
        try:
            with st.spinner("Searching Wikipedia…"):
                result = run_triage(
                    query=None,
                    phrase=None,
                    narrow=[],
                    era=None,
                    seed=None,
                    limit=DEFAULT_LIMIT,
                    output_path=None,
                    articles_path=None,
                    user_agent=user_agent,
                    delay=DEFAULT_DELAY,
                    write_stdout=False,
                )
            st.session_state.search_result = result
            candidates = titles_for_scan(result["rows"])
            st.session_state.scan_titles_text = "\n".join(candidates)
            st.session_state.scan_report = None
        except (ValueError, PermissionError) as exc:
            st.error(str(exc))

    result = st.session_state.search_result
    if result:
        counts = result.get("prioritize", {})
        st.success(
            f"**{result['total']}** results — "
            f"prioritize: **{counts.get('yes', 0)}** yes, "
            f"**{counts.get('maybe', 0)}** maybe, "
            f"**{counts.get('no', 0)}** no"
        )
        st.markdown(
            f"**Query:** `{result['query']}`  \n"
            f"**Era:** `{result['era']}`"
        )
        for warning in result.get("warnings", []):
            st.warning(warning)

        rows = result.get("rows", [])
        if rows:
            _render_triage_results(rows)
            st.download_button(
                "Download triage CSV",
                data=format_triage_csv(rows),
                file_name="triage.csv",
                mime="text/csv",
            )
        
        st.caption(
            "See [search output docs](https://github.com/brittag/WikiTomte-LLM/blob/main/docs/search-triage.md) for CSV column meanings."
        )

        candidate_count = len(titles_for_scan(rows))
        st.info(
            f"**{candidate_count}** article{'s' if candidate_count != 1 else ''} "
            "ready to scan (yes + maybe). Edit the list below to remove any you don't want."
        )

    st.header("2. Scan articles")
    st.markdown(
        """
        Scan articles for suspicious amounts of AI vocabulary. This can take a few minutes (don't close the tab). Note that this method tends to find articles with promotional content and [tone issues](https://en.wikipedia.org/wiki/Wikipedia:Writing_better_articles#Tone) in general, not just LLM-generated text.
        """
    )

    st.text_area(
        "Article titles (one per line)",
        height=150,
        key="scan_titles_text",
        placeholder="Paste article titles here, or run a search above",
    )

    run_scan = st.button("Run scan", type="primary")

    if run_scan:
        titles = parse_article_titles(st.session_state.scan_titles_text)
        if not titles:
            st.error("Add at least one article title to scan.")
        else:
            try:
                with st.spinner(f"Scanning {len(titles)} article(s)… this can take a few minutes"):
                    report = run_batch_from_titles(
                        titles,
                        output_path=None,
                        min_score=DEFAULT_MIN_SCORE,
                        user_agent=user_agent,
                        delay=DEFAULT_DELAY,
                        input_label="web",
                        write_stdout=False,
                    )
                st.session_state.scan_report = report
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))

    report = st.session_state.scan_report
    if report:
        summary = report.get("summary", {})
        st.success(
            f"Scanned **{summary.get('scanned', 0)}** of **{summary.get('total', 0)}** articles — "
            f"**{summary.get('errors', 0)}** errors"
        )

        scan_df = _scan_report_to_display_dataframe(report)
        if not scan_df.empty:
            _render_scan_table(scan_df)
            st.download_button(
                "Download scan report CSV",
                data=format_report_csv(report),
                file_name="report.csv",
                mime="text/csv",
            )

        st.caption(
            "See [scan output docs](https://github.com/brittag/WikiTomte-LLM/blob/main/docs/csv-output.md) for CSV column meanings."
        )

    st.header("Tips and notes")
    st.markdown(
        """
        Skip step 1 if you want to provide a list of articles to scan, such as a list made with [Petscan](https://meta.wikimedia.org/wiki/PetScan/en). Just list the article titles, not the whole URLs.

        [GPTZero Provenance Tool for Wikipedia](https://wikipedia.gptzero.me/) is a free-to-use tool that can help you check a suspicious article, but you need to make your own determination.

        This code is open source: **[WikiTomte-LLM](https://github.com/brittag/WikiTomte-LLM)**. File issues and pull requests in the repository, or write a note at [User talk:Dreamyshade](https://en.wikipedia.org/wiki/User_talk:Dreamyshade).
        
        To run searches with custom vocabulary, or to search and scan a larger number of articles, [use the command-line tool available from the repository](https://github.com/brittag/WikiTomte-LLM#setup).

        This was made by [Dreamyshade](https://en.wikipedia.org/wiki/User:Dreamyshade) based on [Gnomingstuff's guide](https://en.wikipedia.org/wiki/User:Gnomingstuff/Guide_to_finding_AI-generated_text), with [Wikipedia-AI-Skills](https://github.com/fuzheado/Wikipedia-AI-Skills) by [Fuzheado](https://en.wikipedia.org/wiki/User:Fuzheado), using [Cursor](https://en.wikipedia.org/wiki/Cursor_(company)). The web framework is [Streamlit](https://streamlit.io/). Check out [WikiProject AI Tools](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_AI_Tools) if you're interested in using LLMs to help you make tools to help Wikipedia editors.
        
        A [tomte](https://en.wikipedia.org/wiki/Nisse_(folklore)) in Nordic folklore is a [household spirit](https://en.wikipedia.org/wiki/Household_deity), a small person-like creature who lives in your house, a bit like a [gnome](https://en.wikipedia.org/wiki/Wikipedia:WikiGnome), who is mostly helpful but not always. The illustration at top right is by [Jenny Nyström](https://en.wikipedia.org/wiki/Jenny_Nystr%C3%B6m). Like most of her work, it is in the public domain, at least in the United States.
        """
    )

if __name__ == "__main__":
    main()
