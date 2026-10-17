#!/usr/bin/env bash
# Build deploy/artifact/ on this PC (Git Bash on Windows). The box then only installs these wheels; it never builds.
#   bash deploy/pack.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
ART=deploy/artifact
DATA_SRC="${AEI_DATA_DIR:-../../context/data/synthetic_microbiology_dataset}"

rm -rf "$ART"
mkdir -p "$ART/wheels" "$ART/app/data" "$ART/app/cache"

echo "1/4 Linux wheels for Python 3.12 (no compiling on the box)"
cp requirements.txt "$ART/wheels/requirements.txt"
"$PY" -m pip download -q -r requirements.txt -d "$ART/wheels" \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
  --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all:

echo "2/4 App code and static web UI"
cp -r aei web "$ART/app/"
find "$ART/app" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "3/4 Synthetic CSVs (no licence stated in the dataset README: never in git, never offered for download)"
cp "$DATA_SRC"/*.csv "$ART/app/data/"

echo "4/4 Precomputed caches (briefs, signals, narration replay)"
AEI_DATA_DIR="$ART/app/data" AEI_CACHE_DIR="$ART/app/cache" AEI_STATE_DB="$ART/state-pack.sqlite" \
  PYTHONPATH=. "$PY" -m aei.precompute --weeks all
rm -f "$ART/state-pack.sqlite"
find "$ART/app/cache" -name "*.sqlite" -delete

du -sh "$ART"/* | sed 's/^/  /'
echo "Artifact ready: $ART"
