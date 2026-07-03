#!/usr/bin/env bash
# Batch scan Wikipedia articles for LLM-indicator patterns.
# Wraps assets/ai_detector.py with era selection and JSON output.

set -euo pipefail

show_usage() {
    cat <<EOF
Usage: $(basename "$0") <articles-file> --era ERA [options]

Scan a list of Wikipedia article titles for LLM-indicator patterns
(vocabulary, phrases, section headers) from a chosen era band.

ARGUMENTS:
  articles-file   Text file with one article title per line (# for comments)

OPTIONS:
  --era ERA       Required. One of: gpt4, gpt4o, gpt5, grok
  -o, --output F  Write JSON report to file (default: stdout)
  --min-score N   Flag threshold 0.0-1.0 (default: 0.4)
  --delay N       Seconds between API requests (default: 0.5)
  --verbose       Enable debug logging
  -h, --help      Show this help and exit

EXAMPLES:
  $(basename "$0") articles.txt --era gpt4o --output report.json
  $(basename "$0") examples/articles.txt --era gpt4 --min-score 0.5 -o out.json
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
