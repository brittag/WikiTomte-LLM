# Search triage CSV columns

The search triage tool runs a single CirrusSearch query per invocation and writes a CSV for manual review before deep-scanning articles.

## Workflow

```bash
# Step 1: Search + triage
python3 assets/search_triage.py --random \
  -o triage.csv --write-articles candidates.txt

# Review triage.csv; edit candidates.txt to remove false positives

# Step 2: Deep scan (existing tool)
./scripts/batch-ai-scan.sh candidates.txt -o report.csv
```

## Query modes

| Mode | Example |
|------|---------|
| Random | `--random` |
| Era builder (random era) | `--phrase "crucial role" --narrow underscore emphasizing` |
| Era builder (fixed era) | `--era gpt4o --phrase "crucial role" --narrow underscore` |
| Freeform | `--query '"crucial role" emphasize underscore' --era gpt4o` |

**`--random`** picks an era (skipping eras with no phrases), a target phrase from that era, and 2 narrowers from its vocab. Use `--seed` to reproduce the draw.

**One era per query.** The era builder picks randomly from `gpt4`, `gpt4o`, `gpt5`, `grok` when `--era` is omitted.

Freeform `--query` requires `--era` for snippet indicator scanning.

## Columns

| Column | Description |
|--------|-------------|
| `title` | Article title (use in `articles.txt` for batch scan) |
| `pageid` | Wikipedia page ID |
| `url` | Link to article |
| `prioritize` | `yes` = extra indicators or header hit; `maybe` = query terms only; `no` = likely false positive or already tagged with `{{AI-generated}}` |
| `ai_tagged` | `yes` if the article lead contains `{{AI-generated}}` (including `{{AI-generated|date=...}}`); `no` otherwise. Tagged articles are deprioritized (`prioritize=no`) but remain in the CSV |
| `era` | Era band used for snippet indicator scan |
| `query` | Full CirrusSearch query executed |
| `score` | CirrusSearch relevance score |
| `wordcount` | Article word count |
| `section` | Section title from search hit (if any) |
| `snippet` | Search excerpt with HTML stripped |
| `query_terms` | Indicators from your query found in the snippet |
| `extra_indicators` | Additional era indicators in snippet not in the query |
| `section_header_hit` | Suspicious section header matched |

## Interpreting results

- **`prioritize=yes`** — Open the article. The snippet contains AI indicators beyond your search terms.
- **`prioritize=maybe`** — Skim the snippet; may be a weak hit or only query-term matches.
- **`prioritize=no`** — Likely false positive (e.g. "Foster" in title when searching for "foster"), or already tagged with `{{AI-generated}}` (`ai_tagged=yes`).
- **Result count** — The tool warns if fewer than 10 or more than 500 results (doc suggests dozens to hundreds).

## Configuration

A User-Agent is required in `config.json`. Copy `config.example.json` to `config.json` and set your contact info — the tool refuses to run without it or with the placeholder value still in place.

## Example freeform queries

Use `--query` with `--era` to run hand-crafted CirrusSearch strings:

| Style | Era | Query |
|-------|-----|-------|
| WP:AILEGACY / WP:SUPERFICIAL | `gpt4o` | `"crucial role" emphasize underscore` |
| WP:AIDISCLAIMER | `gpt5` | `"not widely documented"` |
| GPT-4 sentence-initial Additionally | `gpt4` | `insource:/Additionally\, / delve meticulously` |

Queries containing `insource:` regex are slow and taxing on Wikimedia servers — use sparingly and pair with other keywords.
