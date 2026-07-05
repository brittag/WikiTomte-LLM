# WikiTomte-LLM

This tool is an experiment in auto-identifying potential undetected LLM-generated text in Wikipedia articles. It produces prioritized lists of suspicious articles for editors to review. The intent is to help editors who want to identify and remove LLM content, especially the dedicated volunteers of [WikiProject AI Cleanup](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_AI_Cleanup), by speeding up their work and making it more fun.

What you can do with this tool:

1. **Create a candidate article list.** Run a command to create a list of articles with potential LLM-generated text by searching all articles for random combinations of AI vocabulary. You get a CSV of search results and a plain-text list of article names.
1. **Scan articles to find suspicious passages.** Run another command to scan each article on the list for significant LLM vocabulary overall and particularly suspicious passages. You get a CSV with all of the data for review.

You can skip directly to scanning if you want to provide your own list of articles to scan, such as a list you made using [Petscan](https://meta.wikimedia.org/wiki/PetScan/en).

You can import CSVs into Google Sheets or another spreadsheet application to sort, filter, and make decisions.

The process is based on [User:Gnomingstuff's guide to finding AI-generated text](https://en.wikipedia.org/wiki/User:Gnomingstuff/Guide_to_finding_AI-generated_text). It uses the vocabulary lists in [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), supplemented with additional vocabulary lists.

This method tends to find articles with promotional content in general, including some articles with LLM-generated text and other articles that were written by people with [conflicts of interest](https://en.wikipedia.org/wiki/Wikipedia:Conflict_of_interest).

This tool was vibecoded by [User:Dreamyshade](https://en.wikipedia.org/wiki/User:Dreamyshade), with [Wikipedia-AI-Skills](https://github.com/fuzheado/Wikipedia-AI-Skills) made by [User:Fuzheado](https://en.wikipedia.org/wiki/User:Fuzheado), using [Cursor](https://en.wikipedia.org/wiki/Cursor_(company)). It is called WikiTomte-LLM because a [tomte](https://en.wikipedia.org/wiki/Nisse_(folklore)) in Nordic folklore is a small person-like creature who lives in your house, a bit like a [gnome](https://en.wikipedia.org/wiki/Wikipedia:WikiGnome), who is mostly helpful but not always.

## Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json with your User-Agent contact info
```

A User-Agent is required in `config.json`, per [Wikimedia's User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy). Copy `config.example.json` to `config.json` and replace the placeholder with your real contact info.

## Quick start

**Step 1 — Search and triage.** Find candidate articles via Wikipedia search; review snippets before fetching full article text.

```bash
python3 assets/search_triage.py --random \
  -o triage.csv --write-articles candidates.txt
```

Review `triage.csv`. Edit `candidates.txt` to remove false positives. See [docs/search-triage.md](docs/search-triage.md) for column meanings.

**Step 2 — Scan.** Scan remaining candidates for suspicious passages across all era vocabulary lists.

```bash
python3 assets/ai_detector.py candidates.txt -o report.csv
```

See [docs/csv-output.md](docs/csv-output.md) for scan report column meanings.

## Scan a list of articles (skip search)

If you already have a list of articles that you want to scan:

```bash
python3 assets/ai_detector.py articles.txt -o report.csv
```

See [examples/articles.txt](examples/articles.txt) for the input format (one title per line; `#` for comments).

## Advanced options

### Custom search queries

`--random` is the easiest starting point. If you want to search using your own CirrusSearch strings, use `--query` with `--era`:

```bash
python3 assets/search_triage.py \
  --query '"crucial role" emphasize underscore' --era gpt4o \
  -o triage.csv --write-articles candidates.txt
```

More query modes and examples: [docs/search-triage.md](docs/search-triage.md).

### Scan options

Restrict to one era band (`gpt4`, `gpt4o`, `gpt5`, `grok`, or `generic`):

```bash
python3 assets/ai_detector.py articles.txt --era gpt4o -o report.csv
```

JSON output and other flags (`--min-score`, `--delay`): [docs/csv-output.md](docs/csv-output.md).
