#!/usr/bin/env bash
# Проверка проекта в чистом окружении (локально и в CI). Без ключей и без сети к платным API.
#   bash scripts/check.sh            # использует .venv
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"; [ -x "$PY" ] || PY=".venv/Scripts/python.exe"
export PYTHONUTF8=1 PYTHONPATH=.
step() { echo; echo "▶ $*"; }
step "import зависимостей";   "$PY" -c "import yaml, requests, numpy, openpyxl, PIL; print('ok')"
step "compileall";            "$PY" -m compileall -q src
step "unit tests";            "$PY" -W ignore -m unittest discover -s tests
step "demo niche_scan";       "$PY" -m src.niche_scan --demo > /dev/null
step "demo discover";         "$PY" -m src.discover --demo > /dev/null
step "saleflow_eval selftest";"$PY" -m src.saleflow_eval selftest
step "monte carlo smoke";     "$PY" -m src.monte_carlo --buyer 1390 --spp 18 --yuan 10 --kg 0.3 --vol 1 --com 26 --buyout 83 --runs 300 > /dev/null
step "learning smoke";        "$PY" -m src.learning review
step "decision smoke";        "$PY" -m src.decision
echo; echo "✅ все проверки прошли"
