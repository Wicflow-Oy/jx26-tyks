# Tyks demo (placeholder name in aei/config.py APP_NAME). One container: FastAPI serves the API and the static web UI.
# The box never compiles or downloads packages: deploy/pack.sh (run on the PC) vendors Linux wheels, the app code,
# the synthetic CSVs and the precomputed caches into deploy/artifact/. This build only installs from those wheels.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY deploy/artifact/wheels /tmp/wheels
RUN pip install --no-index --no-cache-dir --find-links /tmp/wheels -r /tmp/wheels/requirements.txt \
 && rm -rf /tmp/wheels

COPY deploy/artifact/app/ /app/
RUN useradd --system --uid 10001 --home /app app && chown -R app /app
USER app

# Public defaults; the box's .env can override (never put keys here).
ENV AEI_PUBLIC=1 \
    AEI_NARRATOR=replay \
    AEI_DATA_DIR=/app/data \
    AEI_CACHE_DIR=/app/cache \
    AEI_STATE_DB=/tmp/state.sqlite \
    AEI_DAILY_SPEND_USD=20

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=5).status == 200 else 1)"

# No access log: query strings and bodies are never logged. Only Traefik can reach the port (no published ports).
CMD ["uvicorn", "aei.api:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1", \
     "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
