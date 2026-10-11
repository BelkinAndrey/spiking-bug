#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# Do not use Apple's system Python or overwrite an environment copied from Windows.
if [[ -e .venv && ! -x .venv/bin/python ]]; then
    echo "Несовместимая .venv. Переименуйте её и повторите ./setup.sh." >&2
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    python_bin="${PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
        for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
            if command -v "$candidate" >/dev/null 2>&1 &&
                "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
                python_bin="$candidate"
                break
            fi
        done
    fi
    if [[ -z "$python_bin" ]]; then
        echo "Нужен Python 3.10+. Установите Python 3.13: brew install python@3.13" >&2
        echo "Или укажите интерпретатор: PYTHON=/path/to/python3 ./setup.sh" >&2
        exit 1
    fi
    "$python_bin" -c 'import sys; sys.exit("Нужен Python 3.10+") if sys.version_info < (3, 10) else None'
    "$python_bin" -m venv .venv
fi

.venv/bin/python -c 'import sys; sys.exit("В .venv нужен Python 3.10+. Переименуйте её и повторите установку.") if sys.version_info < (3, 10) else None'
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [[ "${1:-}" == "--gpu" ]]; then
    .venv/bin/python -m pip install -r requirements-gpu.txt
fi
if ! command -v node >/dev/null 2>&1; then
    echo "Установите Node.js 22.12+ или 24 LTS и повторите ./setup.sh" >&2
    exit 1
fi
node -e 'const [major, minor]=process.versions.node.split(".").map(Number);if(major<22||(major===22&&minor<12))process.exit(1)' || { echo 'Нужен Node.js 22.12+ или 24 LTS'; exit 1; }
npm ci
npm run build
echo "Готово. Запуск: ./run.sh"
