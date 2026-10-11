#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
    echo "Сначала подготовьте окружение: ./setup.sh" >&2
    exit 1
fi
exec .venv/bin/python scripts/dev.py "$@"
