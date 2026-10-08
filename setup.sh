#!/usr/bin/env bash
# macOS / Linux տեղադրում։ Գործարկում՝  bash setup.sh
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
echo "▶ Python ստուգում…"
"$PY" --version || { echo "❌ Python 3.10+ չկա։ Տեղադրիր՝ https://www.python.org/downloads/"; exit 1; }

echo "▶ Վիրտուալ միջավայր (.venv)…"
"$PY" -m venv .venv

echo "▶ Փաթեթներ…"
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt -q

if [ ! -f .env ]; then
  cp .env.example .env
  echo "▶ Ստեղծվեց .env — բացիր և դիր թոքենները"
fi

echo "▶ Demo գործարկում (առանց API-ի)…"
.venv/bin/python -m src.niche_scan --demo

cat <<'EOT'

════════════════════════════════════════════════════════════
✅ Պատրաստ է։

Հաջորդ քայլերը՝
  1. Բացիր .env ֆայլը և դիր MPSTATS_TOKEN-ը
  2. Ստուգիր՝   .venv/bin/python -m src.mpstats_client limit
  3. Գործարկիր՝ .venv/bin/python -m src.niche_scan --path "Дом/Кухня" --dry-run
  4. Claude Code՝ այս պանակում գրիր  claude  →  /niche-scan Дом/Кухня
════════════════════════════════════════════════════════════
EOT
