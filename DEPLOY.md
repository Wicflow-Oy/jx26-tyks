# Deploying the Tyks demo (for the operator)

**What it is:** a public demo for JunctionX Turku (Tyks x Mylab track): a weekly antibiotic-resistance brief for infection control, a ward view and a mocked order screen. One container serves the web UI and the API at one hostname. The hostname placeholder is `tyks-demo.demo.wicflow.com` until the team picks the name.
- **Compose project:** `jx-tyks`. Container: `jx-tyks`. Volume: `jx-tyks_tyks-cache`. 1 GB memory, 1 CPU.
- **The build is light:** `python:3.12-slim` plus binary wheels only (about 70 MB of packages, no compiling).
- **The dataset is not in git or in the image.** The 6 synthetic CSVs (1.5 MB) are copied to the box once and mounted read-only (step 2).
- **What it stores and logs:** it stores only an ephemeral demo state in `/tmp` inside the container and a cache volume. It has no access log and no request bodies in logs. Every response carries `X-Robots-Tag: noindex`.
- **No key needed:** with no key the demo runs on precomputed narration and makes no model calls. With a key, live calls are capped at $20/day and rate-limited per IP.

**Production rules:**
- Treat the box as production, because it runs the other internal services.
- Only ever run commands with `-p jx-tyks`.
- Never touch other compose projects, their containers or networks, or the proxy's own config.
- Never restart Traefik, Caddy or nginx.

## 0. Read-only preflight (changes nothing)
```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}"
```
```bash
sudo ss -ltnp | grep -E ':(80|443)\s'
```
```bash
docker network ls
```
```bash
df -h /
```
```bash
free -m
```
```bash
docker compose version
```
**Decide from the output:**
- **Who owns 80/443?** A `traefik` container → **case A**. A host `caddy` or `nginx` process → **case B**.
- **Case A: Traefik's network, entrypoint and cert resolver:**
  ```bash
  docker inspect <traefik-container> --format '{{json .NetworkSettings.Networks}}'
  ```
  ```bash
  docker inspect <traefik-container> --format '{{json .Args}}'
  ```
  Look for the network (wicflow.com's setup uses `n8n_default`), the TLS entrypoint (usually `websecure`) and the resolver (`zerossl` there).
- **Memory:** about 1.2 GB free for the 1 GB container. **Disk:** about 400 MB for the image and cache.
- **Compose:** 2.24 or newer (the compose file uses `env_file` with `required`).
- **Case B only:** check that port 8765 is free.
  ```bash
  sudo ss -ltnp | grep 8765
  ```
  If it's taken, set `TYKS_PORT` in `.env`.

## 1. Get the code
Repo URL: the private Wicflow-Oy repo, once the team lead creates it.
```bash
sudo mkdir -p /opt/jx && sudo chown "$USER" /opt/jx && git clone <repo-url> /opt/jx/tyks
```
```bash
cd /opt/jx/tyks
```

## 2. The dataset (first time only)
the team lead sends `synthetic_microbiology_dataset.zip` (the partner's file from the event Discord, 1.51 MB). Unzip it so the CSVs sit directly in `/opt/jx/tyks/data/`:
```bash
mkdir -p /opt/jx/tyks/data && unzip -j synthetic_microbiology_dataset.zip '*.csv' -d /opt/jx/tyks/data && ls /opt/jx/tyks/data
```
Expect 6 files: `antibiotics.csv`, `cultures.csv`, `isolates.csv`, `patients.csv`, `susceptibility.csv` and `wards.csv`. The data is synthetic. Its README states no licence, so it stays out of git and is never offered for download by the app.

## 3. Secrets and settings (first time only)
```bash
cp .env.example .env && chmod 600 .env
```
Fill in `.env`:
- **`TYKS_HOST`:** the hostname. With no DNS yet, use `tyks-demo.<server-ip>.sslip.io`.
- **Case A:** `TRAEFIK_NETWORK`, `TYKS_CERTRESOLVER` and `TRAEFIK_ENTRYPOINT`, from the preflight.
- **Case B:** `TYKS_PORT`, if 8765 is taken.
- **`ANTHROPIC_API_KEY`:** optional; this app's own key, from the team lead. Leave `AEI_NARRATOR` empty, which means precomputed narration, unless the team lead asks for live narration.

Leave everything else empty to use the defaults. Never paste the key into chat, git or logs.

## 4a. Case A: Traefik (Docker labels)
```bash
docker compose -p jx-tyks -f deploy/compose.yml -f deploy/compose.traefik.yml --env-file .env up -d --build
```
This attaches only to Traefik's existing network, with no host ports. Router, service and middleware names all start with `jx-tyks`.

## 4b. Case B: Caddy or nginx on the host
```bash
docker compose -p jx-tyks -f deploy/compose.yml -f deploy/compose.port.yml --env-file .env up -d --build
```
This publishes on `127.0.0.1:8765` only. Add **one** site block for this hostname, and don't edit other sites.

**Caddy:**
```
tyks-demo.demo.wicflow.com {
	reverse_proxy 127.0.0.1:8765
	header X-Robots-Tag "noindex, nofollow"
	request_body {
		max_size 1MB
	}
}
```
Then:
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```
```bash
sudo systemctl reload caddy
```

**nginx** (TLS via your usual certbot flow):
```
server {
    server_name tyks-demo.demo.wicflow.com;
    client_max_body_size 1m;
    add_header X-Robots-Tag "noindex, nofollow" always;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Then:
```bash
sudo nginx -t
```
```bash
sudo systemctl reload nginx
```
A reload, not a restart.

## 5. Verify
The first start precomputes the demo weeks, which takes about a minute, so the container shows `starting` until the healthcheck passes.
```bash
docker compose -p jx-tyks ps
```
```bash
curl -s https://tyks-demo.demo.wicflow.com/api/health
```
```bash
curl -sI https://tyks-demo.demo.wicflow.com/ | grep -i -E "^HTTP|x-robots-tag"
```
- **Health:** expect `"ok": true`, `"data_loaded": true` and `"key_set": true` or `false`. The key itself is never shown.
  - `data_loaded: false` means step 2 is missing: check `ls /opt/jx/tyks/data`.
- **Headers:** expect HTTP 200 and `x-robots-tag: noindex`.

**Logs** (startup and errors only; no requests):
```bash
docker logs --tail 50 jx-tyks
```

## 6. Update to a new release
```bash
cd /opt/jx/tyks && docker tag jx-tyks:live jx-tyks:prev && git pull
```
Then run the same `up -d --build` command as in 4a or 4b.

## 7. Roll back or remove (this project only)
**Back to the previous image** (case A shown; use `compose.port.yml` for case B):
```bash
TYKS_TAG=prev docker compose -p jx-tyks -f deploy/compose.yml -f deploy/compose.traefik.yml --env-file .env up -d --no-build
```
**Stop and remove this demo:**
```bash
docker compose -p jx-tyks -f deploy/compose.yml -f deploy/compose.traefik.yml --env-file .env down
```
Add `-v` to also delete its cache volume. In case B, also remove its Caddy or nginx site block and reload. Nothing else on the box is affected.

## Not yet verified
**Docker isn't installed on the build PC,** so this image has not been built or run locally yet. The app is tested with uvicorn and pytest on the PC. Report anything that fails at `--build` to the team, and don't patch other services to make it work.
