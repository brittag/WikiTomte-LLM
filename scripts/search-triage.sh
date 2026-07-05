#!/usr/bin/env bash
# Search Wikipedia for LLM-indicator patterns and export triage CSV + articles list.

set -euo pipefail

show_usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Search Wikipedia via CirrusSearch for LLM-indicator patterns and export
a triage CSV for review, plus an optional articles.txt for batch-ai-scan.

OPTIONS:
  --random          Pick era, phrase, and 2 narrowers from ai_vocab.json
  --query TEXT      Raw CirrusSearch query (requires --era)
  --phrase TEXT     Target phrase for era builder
  --narrow WORDS    Narrowing vocab words (era builder)
  --era ERA         gpt4, gpt4o, gpt5, or grok (random if omitted in era builder)
  --seed N          Seed for reproducible --random or era-builder era selection
  -o, --output F    Write triage CSV to file (default: stdout)
  --write-articles F  Write article titles for batch-ai-scan.sh
  --limit N         Max search results (default: 100)
  --delay N         Seconds between API requests (default: 0.5)
  --verbose         Enable debug logging
  -h, --help        Show this help and exit

EXAMPLES:
  $(basename "$0") --random -o triage.csv --write-articles candidates.txt
  $(basename "$0") --query '"crucial role" emphasize underscore' --era gpt4o -o triage.csv
  $(basename "$0") --phrase "crucial role" --narrow underscore emphasizing -o triage.csv
EOF
    exit 0
}

if [ $# -eq 0 ]; then
    show_usage
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TRIAGE="${SCRIPT_DIR}/../assets/search_triage.py"

if [ ! -f "$TRIAGE" ]; then
    echo "Error: search_triage.py not found at $TRIAGE" >&2
    exit 1
fi

exec python3 "$TRIAGE" "$@"
