# Strainwatch. One container: FastAPI serves the API and the static web UI.
# Built from the repo on the server. Light build: binary wheels only (no compiling), ~70 MB of packages.
# The synthetic dataset is NOT in the image or in git: it is bind-mounted read-only at /app/data (see DEPLOY.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY aei/ /app/aei/
COPY web/ /app/web/
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN useradd --system --uid 10001 --home /app app \
 && mkdir -p /app/cache /app/data \
 && chmod 755 /app/entrypoint.sh \
 && chown -R app /app/cache

USER app

# Public defaults; .env on the server can override. Never put keys here.
ENV AEI_PUBLIC=1 \
    AEI_NARRATOR=replay \
    AEI_DATA_DIR=/app/data \
    AEI_CACHE_DIR=/app/cache \
    AEI_STATE_DB=/tmp/state.sqlite \
    AEI_DAILY_SPEND_USD=20 \
    PORT=8765

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8765'), timeout=5).status == 200 else 1)"

CMD ["/app/entrypoint.sh"]
