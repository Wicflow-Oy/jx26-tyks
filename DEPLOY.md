# Deploy

How the operator runs the public demo on a Linux host with Docker. One container serves the web UI and the API at one
hostname, behind the host's existing reverse proxy.

- **Compose project:** `jx-tyks`. Container: `jx-tyks`. Volume: `jx-tyks_tyks-cache`. Limits: 1 GB memory, 1 CPU.
- **The build is light:** `python:3.12-slim` plus binary wheels only (no compiler needed).
- **The dataset is not in git or in the image.** The 6 synthetic CSVs (1.5 MB) are copied to the host once and mounted
  read-only (step 2).
- **What it stores and logs:** demo state in `/tmp` inside the container (gone on restart) and precomputed caches in a
  volume. No access log and no request bodies in logs. Every response carries `X-Robots-Tag: noindex, nofollow`.
- **No key needed:** without `ANTHROPIC_API_KEY` the app makes no model calls; texts come from the fixed templates (or
  from wording recorded earlier, step 5). With a key, live calls are capped at $20 a day and rate-limited per IP.

**Safety** (the host may run other services):
- Every command here names the project (`-p jx-tyks`) and touches nothing else.
- The proxy keeps running: at most one added site block and a reload.

This guide uses `/opt/jx/tyks` as the folder and `<host>` for the public hostname (the `TYKS_HOST` value).

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
- **Who owns 80/443?** A `traefik` container: **case A**. A host `caddy` or `nginx` process: **case B**.
- **Case A: Traefik's network, entrypoint and cert resolver:**
  ```bash
  docker inspect <traefik-container> --format '{{json .NetworkSettings.Networks}}'
  ```
  ```bash
  docker inspect <traefik-container> --format '{{json .Args}}'
  ```
  Note the network, the TLS entrypoint and the cert resolver; step 3 puts them in `.env` (the entrypoint defaults to
  `websecure`).
- **Memory:** about 1.2 GB free for the 1 GB container. **Disk:** about 0.5 GB for the image and cache.
- **Compose:** 2.24 or newer (the compose file uses `env_file` with `required`).
- **Case B only:** check that port 8765 is free.
  ```bash
  sudo ss -ltnp | grep 8765
  ```
  If it is taken, set `TYKS_PORT` in `.env`.

## 1. Get the code
```bash
sudo mkdir -p /opt/jx && sudo chown "$USER" /opt/jx && git clone <repo-url> /opt/jx/tyks
```
```bash
cd /opt/jx/tyks
```

## 2. The dataset (first time only)
Use the challenge's `synthetic_microbiology_dataset.zip` (1.5 MB, from the organisers). Unzip it so the CSVs sit
directly in `/opt/jx/tyks/data/`:
```bash
mkdir -p /opt/jx/tyks/data && unzip -j synthetic_microbiology_dataset.zip '*.csv' -d /opt/jx/tyks/data && ls /opt/jx/tyks/data
```
Expect 6 files: `antibiotics.csv`, `cultures.csv`, `isolates.csv`, `patients.csv`, `susceptibility.csv` and
`wards.csv`. The data is synthetic. Its README states no licence, so it stays out of git and the app never offers it
for download. To keep it elsewhere, set `TYKS_DATA_DIR`.

## 3. Settings (first time only)
```bash
cp .env.example .env && chmod 600 .env
```
Fill in `.env`; every variable is described in `.env.example`, and an empty value means the default.
- **`TYKS_HOST`:** the hostname. Without DNS, `strainwatch.<server-ip>.sslip.io` works.
- **Case A:** `TRAEFIK_NETWORK` and `TYKS_CERTRESOLVER` (required), and `TRAEFIK_ENTRYPOINT`, from the preflight.
- **Case B:** `TYKS_PORT`, if 8765 is taken.
- **`ANTHROPIC_API_KEY`:** optional, a key for this app only. Leave `AEI_NARRATOR` empty: in public mode that means
  `replay` (wording recorded earlier, see step 5, else the templates), with no live calls. Set it to `anthropic` only
  for live wording, within the daily cap.

Keys stay in `.env` on the host: never in git, chat or logs.

## 4a. Case A: Traefik (Docker labels)
```bash
docker compose -p jx-tyks -f deploy/compose.yml -f deploy/compose.traefik.yml --env-file .env up -d --build
```
This attaches only to Traefik's existing network, with no host ports. Router, service and middleware names all start
with `jx-tyks`.

## 4b. Case B: Caddy or nginx on the host
```bash
docker compose -p jx-tyks -f deploy/compose.yml -f deploy/compose.port.yml --env-file .env up -d --build
```
This publishes on `127.0.0.1:8765` only. Add **one** site block for this hostname, and do not edit other sites.

**Caddy:**
```
<host> {
	reverse_proxy 127.0.0.1:8765
	header X-Robots-Tag "noindex, nofollow"
	request_body {
		max_size 64KB
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

**nginx** (TLS through the host's usual certbot flow):
```
server {
    server_name <host>;
    client_max_body_size 64k;
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
The first start precomputes the demo weeks (about a minute), so the container shows `starting` until the healthcheck
passes.
```bash
docker compose -p jx-tyks ps
```
```bash
curl -s https://<host>/api/health
```
```bash
curl -sI https://<host>/ | grep -i -E "^HTTP|x-robots-tag"
```
- **Health:** expect `"ok": true`, `"data_loaded": true` and `"key_set": true` or `false`. The key itself is never
  shown. `data_loaded: false` means step 2 is missing: check `ls /opt/jx/tyks/data`.
- **Headers:** expect HTTP 200 and `x-robots-tag: noindex, nofollow`.

**Logs** (startup and errors only; no requests):
```bash
docker logs --tail 50 jx-tyks
```

**Optional, with a key:** record model wording for the demo weeks once, so `replay` shows it without live calls. The
calls count toward the daily cap; the recordings live in the cache volume.
```bash
docker exec jx-tyks python -m aei.precompute --weeks demo --narration
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
**Stop and remove the demo:**
```bash
docker compose -p jx-tyks -f deploy/compose.yml -f deploy/compose.traefik.yml --env-file .env down
```
Add `-v` to also delete its cache volume. In case B, also remove its Caddy or nginx site block and reload. Nothing else
on the host is affected.

If `--build` fails, nothing else on the host has changed: fix the build and run the same command again.
