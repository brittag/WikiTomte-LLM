# Auto-gnome

This tool is an experiment in auto-identifying potential undetected LLM-generated text in Wikipedia articles. It produces prioritized lists of suspicious articles for editors to review. The goal is to support the dedicated volunteers of [WikiProject AI Cleanup](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_AI_Cleanup) by automating parts of their workflow.

Overview of process:

1. **Create a candidate article list.** Run a command to create a list of articles with potential LLM-generated text by searching all articles for random combinations of AI vocabulary. You get a CSV of search results and a plain-text list of article names.
1. **Scan articles to find suspicious passages.** Run another command to scan each article on the list for significant LLM vocabulary overall and particularly suspicious passages. You get a CSV with all of the data for review.

You can skip directly to scanning if you want to provide your own list of articles to scan, such as a list you made using [Petscan](https://meta.wikimedia.org/wiki/PetScan/en).

You can import CSVs into Google Sheets or another spreadsheet application to sort, filter, and make decisions.

The process is based on [User:Gnomingstuff's guide to finding AI-generated text](https://en.wikipedia.org/wiki/User:Gnomingstuff/Guide_to_finding_AI-generated_text). It uses the vocabulary lists in [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), supplemented with additional vocabulary lists.

This method tends to find articles with promotional content in general, including some articles with LLM-generated text and other articles that were written by people with [conflicts of interest](https://en.wikipedia.org/wiki/Wikipedia:Conflict_of_interest).

This tool was vibecoded by [User:Dreamyshade](https://en.wikipedia.org/wiki/User:Dreamyshade) using [Cursor](https://en.wikipedia.org/wiki/Cursor_(company)).


## Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json with your User-Agent contact info
```

A User-Agent is required in `config.json`, per [Wikimedia's User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy). Copy `config.example.json` to `config.json` and replace the placeholder with your real contact info.

## Two-step workflow

### Step 1: Search + triage

Find candidate articles via Wikipedia search and review snippets before fetching full text.

```bash
# Random era + phrase + narrowers (easiest)
python3 assets/search_triage.py --random \
  -o triage.csv --write-articles candidates.txt

# Curated preset query
python3 assets/search_triage.py --preset gpt4o-legacy \
  -o triage.csv --write-articles candidates.txt

# Shell wrapper
./scripts/search-triage.sh --random -o triage.csv --write-articles candidates.txt
```

Review `triage.csv` and edit `candidates.txt` to remove false positives. See [docs/search-triage.md](docs/search-triage.md) for column reference.

### Step 2: Scan

Scan surviving candidates against all era vocab lists.

```bash
python3 assets/ai_detector.py candidates.txt -o report.csv
# Or: ./scripts/batch-ai-scan.sh candidates.txt -o report.csv
```

See [docs/csv-output.md](docs/csv-output.md) for scan report columns.

## Direct scan (skip search)

If you already have an article list:

```bash
# Create a text file with one Wikipedia article title per line (# for comments)
python3 assets/ai_detector.py articles.txt -o report.csv
```

See [examples/articles.txt](examples/articles.txt) for a sample.

By default each article is scanned against all era bands: `gpt4`, `gpt4o`, `gpt5`, `grok`, and `generic`. Restrict to one era with `--era`:

```bash
python3 assets/ai_detector.py articles.txt --era generic -o report.csv
```

For JSON output, add `--json`:

```bash
python3 assets/ai_detector.py articles.txt --json -o report.json
```
