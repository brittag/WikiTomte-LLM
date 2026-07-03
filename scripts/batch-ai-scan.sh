#!/usr/bin/env bash
# Batch scan Wikipedia articles for LLM-indicator patterns.
# Wraps assets/ai_detector.py with era selection and CSV/JSON output.

set -euo pipefail

show_usage() {
    cat <<EOF
Usage: $(basename "$0") <articles-file> [options]

Scan a list of Wikipedia article titles for LLM-indicator patterns
(vocabulary, phrases, section headers). All era bands are scanned by default.

ARGUMENTS:
  articles-file   Text file with one article title per line (# for comments)

OPTIONS:
  --era ERA       Scan only one era: gpt4, gpt4o, gpt5, grok, or generic (default: all)
  -o, --output F  Write report to file (default: stdout)
  --json          Output JSON instead of CSV (default: CSV)
  --min-score N   Flag threshold 0.0-1.0 (default: 0.4)
  --delay N       Seconds between API requests (default: 0.5)
  --verbose       Enable debug logging
  -h, --help      Show this help and exit

EXAMPLES:
  $(basename "$0") articles.txt --output report.csv
  $(basename "$0") articles.txt --era gpt4o --output report.csv
  $(basename "$0") examples/articles.txt --json -o report.json
EOF
    exit 0
}

if [ $# -eq 0 ]; then
    show_usage
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECTOR="${SCRIPT_DIR}/../assets/ai_detector.py"

if [ ! -f "$DETECTOR" ]; then
    echo "Error: ai_detector.py not found at $DETECTOR" >&2
    exit 1
fi

exec python3 "$DETECTOR" "$@"
