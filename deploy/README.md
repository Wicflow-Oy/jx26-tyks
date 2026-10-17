# Deploying the public demo (UpCloud, Helsinki)

The shared conventions are in `../../HOSTING.md`.
- **Compose project:** `jx-tyks`, behind the box's existing Traefik.
- **Hostname:** placeholder `tyks-demo.demo.wicflow.com` until the name is decided.
- **Limits and privacy:** 1 GB memory, no published ports, `noindex` headers, and no access or request-body logging.

## Before deploying: wait for the team lead's three confirmations
1. **Is it the same box as wicflow.com?** If yes, it's production:
   - touch only `jx-tyks`;
   - never touch `wicflow-site`, never touch Traefik's config, and never restart Traefik.

   That box "never builds" heavy images, so this image only installs wheels that were downloaded on the PC.
2. **DNS:** `tyks-demo.demo.wicflow.com`, or a `*.demo.wicflow.com` wildcard, must point at the box. Until then, set `TYKS_HOST=tyks-demo.<server-ip>.sslip.io` in `.env`.
3. **SSH:** the team lead gives the host alias this PC uses (called `jxbox` below), or runs the first deploy himself. Nobody creates users or keys on the box.

Also check two things on the box and set them in `.env` if they differ:
- the Traefik network name (`docker network ls`; wicflow-site uses `n8n_default`) → `TRAEFIK_NETWORK`;
- the cert resolver (`zerossl` there) → `TYKS_CERTRESOLVER`.

**Docker isn't installed on this PC,** so the image hasn't been built or run locally. The app itself is tested with uvicorn on the PC. The first `docker compose up --build` on the box is the image's first build. It only runs `pip install` from local wheels: no compiling and no downloads.

## 1. Build the artifact on this PC
```bash
bash deploy/pack.sh
```
This creates `deploy/artifact/`, which contains:
- Linux wheels for Python 3.12;
- the app code and web UI;
- the synthetic CSVs (never in git);
- the precomputed caches.

## 2. Upload (mirrors the repo layout under /opt/jx/tyks)
```bash
tar czf - Dockerfile .dockerignore deploy/compose.yml deploy/artifact | ssh jxbox "mkdir -p /opt/jx/tyks && tar xzf - -C /opt/jx/tyks"
```

## 3. Secrets (first time only, on the box)
Create `/opt/jx/tyks/.env` from `deploy/.env.example`. The key is optional: the demo runs on precomputed narration without one. If you use one, use this app's own Claude key (its own Console workspace with a spend limit). Then:
```bash
ssh jxbox "chmod 600 /opt/jx/tyks/.env"
```

## 4. Start or update
```bash
ssh jxbox "cd /opt/jx/tyks && docker compose -p jx-tyks -f deploy/compose.yml --env-file .env up -d --build"
```

## 5. Check
```bash
curl -sI https://tyks-demo.demo.wicflow.com/ | grep -i -E "HTTP/|x-robots-tag"
```
```bash
curl -s https://tyks-demo.demo.wicflow.com/api/health
```
The health response shows `key_set` (true/false), today's spend and the cap. It never shows the key.

## Roll back
1. Before updating, tag the current image: `docker tag jx-tyks:live jx-tyks:prev`.
2. To go back, run: `TYKS_TAG=prev docker compose -p jx-tyks -f deploy/compose.yml --env-file .env up -d --no-build`.

## Pitch line
"Hosted in Helsinki (UpCloud), EU data residency" holds for the app and its data. The optional live narration calls go to Anthropic. By default the narration is precomputed, so a judge's visit makes no model call.
