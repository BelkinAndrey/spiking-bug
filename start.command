#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python || ! -d node_modules ]]; then
    ./setup.sh
fi
./run.sh
