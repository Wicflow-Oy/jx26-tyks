# Demo hosting: shared conventions (all three builds)

the team lead's **UpCloud server in Helsinki** hosts all three public demos. Every build session follows this file. One session owns one app and touches nothing else on the server.

## Update, Sat ~20:00 (the team lead)
- **The server runs Wicflow's other internal services and other services.** the team lead isn't sure whether wicflow.com runs there too. **Treat it as production either way.**
- **the operator deploys, not the build sessions.** the operator has the SSH access. When an app is finished and previewed, he pulls it **from GitHub** and runs it on the server. No session SSHes into the server.
- **What each session delivers in its repo:**
  1. a `Dockerfile` and `deploy/compose.yml`, with a healthcheck, a memory limit and no host ports when a reverse proxy exists;
  2. `.env.example`, with every variable named and none filled in;
  3. a `DEPLOY.md` written for the operator:
     - step 0 is a **read-only preflight**: `docker ps`, check what listens on 80/443 (Traefik, Caddy or nginx), `docker network ls`, `df -h` and `free -m`;
     - then the exact commands for each proxy case: Traefik labels, or a published `127.0.0.1:<port>` plus a Caddy or nginx snippet;
     - then how to verify the health URL and how to roll back with `docker compose -p <project> down`;
     - never touch other projects.
- **API keys:** the team lead creates one key per app.
  - Locally, the team lead puts each one in `builds/<app>/.env.local` (gitignored) himself.
  - On the server, the operator copies `.env.example` to `.env` and fills it in.
  - Keys never appear in chat, in git or in logs.

## Still open (the team lead, Sat evening)
1. **Is this the same server that runs wicflow.com?** That site already uses **Traefik** with Docker labels and the cert resolver `zerossl` (see `wicflow-site/docker-compose.yml`).
   - If it is the same server, treat it as **production**:
     - never touch the `wicflow-site` compose project, its containers, or Traefik's own config;
     - never restart Traefik;
     - only add new compose projects that attach to Traefik's existing Docker network.
2. **Domains.** Proposed: `preparedhome.demo.wicflow.com`, `strainwatch.demo.wicflow.com` and `bluewatch.demo.wicflow.com`. the team lead adds the DNS records, either one wildcard `*.demo.wicflow.com` or three A records pointing at the server.
   - There's no `if` in any hostname, so the demo isn't presented as If's.
   - If DNS isn't ready, `<name>.<server-ip>.sslip.io` works without DNS changes.
   - The Tyks name is still open. Use `tyks-demo` as the hostname placeholder until the team lead decides.
3. **SSH.** the team lead confirms the SSH host alias this PC uses, or runs the first deploy himself. No session creates users or keys on the server.

## Conventions
| App | Compose project | Hostname (proposed) | Memory limit |
|---|---|---|---|
| If: Prepared Home | `jx-preparedhome` | preparedhome.demo.wicflow.com | 1 GB |
| Tyks | `jx-tyks` | strainwatch.demo.wicflow.com (name TBD) | 1 GB |
| Redstone: BlueWatch | `jx-bluewatch` | bluewatch.demo.wicflow.com | 1.5 GB |

**Images and deploy**
- Each app ships a `Dockerfile` and a `deploy/compose.yml` with Traefik labels:
  - `traefik.enable=true`;
  - `Host(...)`;
  - `entrypoints=websecure`;
  - `tls.certresolver=zerossl` (if same server; otherwise per that server's setup).
- Each app has a healthcheck, a memory limit and `restart: unless-stopped`.
- No published host ports. Traefik routes everything.
- Build the image locally (or on the box in the app's own folder, `/opt/jx/<app>/`), then `docker compose -p <project> up -d`. Only ever act on your own project name.

**Secrets**
- Each app keeps its own `.env` on the server at `/opt/jx/<app>/.env`. It is never in git, never in a client bundle, and never logged.
- Use **one Claude API key per app** so spend can be tracked and revoked separately. the team lead creates the keys in the Anthropic Console, ideally one workspace per app with a spend limit.

**Public-endpoint guards**
- Rate limits per IP.
- An app-level daily LLM spend cap:
  - If: $40/day;
  - Tyks: $20/day;
  - BlueWatch: $40/day.
- Cached or precomputed fallback when a cap or rate limit hits.
- The budget is $1,100 of Claude credit for building, testing and demos. Routine tests run on mocks and fixtures.

**Every app**
- Sends `X-Robots-Tag: noindex` and shows a visible "Prototype" label.
- Has no analytics or trackers.
- Logs no request bodies (no photos, no entered business IDs).

**Hosting story for the pitch:** "Hosted in Helsinki (UpCloud), EU data residency." This holds for the app and its data. Claude API calls still go to Anthropic, so say so if asked.
