#!/usr/bin/env bash
set -euo pipefail

source venv/bin/activate
exec python run_scrape.py "$@"
