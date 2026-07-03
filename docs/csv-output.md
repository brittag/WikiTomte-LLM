# CSV output columns

The batch scanner writes **CSV by default** (use `--json` for the full structured report). Each row represents one **suspicious passage** within an article, or a summary/error row when no passage applies.

## Row types

| Row type | When it appears |
|----------|-----------------|
| Passage row | Article scanned successfully and at least one match was clustered into a passage |
| Article-only row | Article scanned successfully but produced no passage clusters (rare; usually means no matches) |
| Error row | Article could not be scanned (missing page, API failure, etc.) |

Articles with multiple suspicious passages appear on **multiple rows**. When all eras are scanned (the default), the same article may also appear on multiple rows with different `era` values. Article-level columns (`title`, `flagged`, `suspicion_score`, etc.) are repeated on each passage row for that article–era combination.

## Columns

| Column | Description |
|--------|-------------|
| `title` | Wikipedia article title |
| `pageid` | Wikipedia page ID (stable numeric identifier) |
| `url` | Canonical URL to the article |
| `era` | LLM era band for this row (`gpt4`, `gpt4o`, `gpt5`, `grok`, `generic`, or `all` when no era had matches). By default each article is scanned against all eras; use `--era` to restrict to one |
| `flagged` | `True` if the article met the flag threshold: `suspicion_score` ≥ `--min-score` (default 0.4) **and** at least 2 indicator matches. `False` otherwise. This is a triage hint, not proof of LLM authorship |
| `suspicion_score` | Article-level score from 0.0 to 1.0, based on weighted indicator matches normalized by article length. Higher values mean more/coarser pattern hits |
| `match_count` | Total number of indicator matches found anywhere in the article (across all passages) |
| `text_length` | Length of the article's stripped plain-text prose, in characters |
| `section` | Wikipedia section name where this passage appears (e.g. `Lead`, `Legacy`). Empty on article-only and error rows |
| `passage_score` | Passage-level score from 0.0 to 1.0, based on the weight and density of matches within this clustered passage. Empty on article-only and error rows |
| `passage_text` | Excerpt of article prose surrounding the matched indicators (~200 characters of context on each side). This is the primary column to review manually |
| `indicators` | Semicolon-separated list of matched words/phrases in this passage (e.g. `crucial role; underscore; highlighting`) |
| `indicator_types` | Semicolon-separated match types, parallel to `indicators`. Possible values: `phrase` (multi-word target phrase), `vocab` (single era vocabulary word), `sentence_initial` (e.g. `Additionally,` at sentence start), `section_header` (suspicious section title) |
| `cautions` | Semicolon-separated notes about possible false-positive contexts (e.g. technology or sociology articles where some phrasing is more expected). Informational only — matches are not suppressed |
| `error` | Error message if the article failed to scan. Empty on successful rows |

## Usage notes

- Review `passage_text` and `indicators` together; co-occurring era-appropriate vocabulary in the same section is stronger signal than an isolated hit.
- Compare `era` values across rows for the same article — hits that align with one era but not others can help narrow when text was likely added.
- A `flagged` value of `False` does not mean the article is clean — check rows with matches anyway if your search suggested the article was worth opening.
- For full nested data (all matches with byte offsets, complete passage match lists, run summary), re-run with `--json`.
