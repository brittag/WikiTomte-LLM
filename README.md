This is a simple experiment in identifying potential LLM-generated text in Wikipedia articles using AI vocabulary word lists. It is based on [Gnomingstuff's Guide to finding AI-generated text](https://en.wikipedia.org/wiki/User:Gnomingstuff/Guide_to_finding_AI-generated_text) and vocabulary lists in [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), supplemented with additional vocabulary items.

This is a **triage assistant** — it finds pattern co-occurrence, not proof of LLM authorship. Review flagged passages manually before taking action on an article.

## Setup

```bash
pip install -r requirements.txt
```

Before running at scale, set a real contact in the User-Agent — either edit `DEFAULT_USER_AGENT` in `assets/ai_detector.py` or pass `--user-agent` / set `WIKIMEDIA_USER_AGENT`.

## Input file

Create a text file with one Wikipedia article title per line. Lines starting with `#` are ignored.

```
Albert Einstein
Python (programming language)
```

See `[examples/articles.txt](examples/articles.txt)` for a sample.

## Run

```bash
# CSV report (default) — scans all eras
python3 assets/ai_detector.py articles.txt -o report.csv

# Or use the shell wrapper
./scripts/batch-ai-scan.sh articles.txt -o report.csv
```

By default each article is scanned against all era bands: `gpt4`, `gpt4o`, `gpt5`, `grok`, and `generic`. Restrict to one era with `--era`:

```bash
python3 assets/ai_detector.py articles.txt --era generic -o report.csv
```

## Output

CSV is the default format: one row per suspicious passage, with article metadata, matched indicators, and excerpt text. See `[docs/csv-output.md](docs/csv-output.md)` for a column reference.

For JSON output, add `--json`:

```bash
python3 assets/ai_detector.py articles.txt --json -o report.json
```