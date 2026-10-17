#!/bin/sh
# Warm the caches for the demo weeks (fast), then serve. The full replay range warms in the background.
# If the dataset is missing, the server still starts and /api/health reports data_loaded=false.
set -u
cd /app
if [ -f "${AEI_DATA_DIR:-/app/data}/isolates.csv" ]; then
  python -m aei.precompute --weeks demo || echo "precompute (demo weeks) failed; continuing"
  (python -m aei.precompute --weeks all >/dev/null 2>&1 || echo "precompute (all weeks) failed") &
else
  echo "dataset not found in ${AEI_DATA_DIR:-/app/data}; see DEPLOY.md step 2"
fi
# No access log: query strings and bodies are never logged. Only the proxy reaches this port.
exec uvicorn aei.api:app --host 0.0.0.0 --port "${PORT:-8765}" --workers 1 \
  --no-access-log --proxy-headers --forwarded-allow-ips "*"
