# Deploying Ledgerly

Ledgerly ships as a single-process Docker image (`Dockerfile`, `docker-compose.yml`) so it can be deployed anywhere that runs Docker Compose — a NAS, a VPS, a home server, or your own laptop. There is nothing NAS-specific about the image itself; use whatever deployment tooling and reverse proxy/tunnel setup you already have for exposing a Compose service under a domain.

Deploy status of this repo: the image and Compose file are written and locally verified (see below); no specific hosted deployment is tracked here. If you keep your own deployment notes (real domain, specific host/tooling, credentials-adjacent steps), keep them in a local, gitignored file rather than editing this one — see the note at the bottom.

## Prerequisites

- Docker and Docker Compose installed wherever you're building/running the image.
- A way to expose port 8000 under a domain, if you want this reachable outside your local network — a reverse proxy (Nginx, Traefik, Caddy) or a tunnel (Cloudflare Tunnel, Tailscale Funnel, etc.). Any of these work; Ledgerly doesn't care which.

## Test Locally First

Build and run the image on your own machine before deploying anywhere:

```bash
cp .env.example .env
# edit .env: set both LEDGERLY_API_USERNAME and LEDGERLY_API_PASSWORD to something real
docker compose up --build
```

Then, from another terminal:

```bash
curl http://localhost:8000/health
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"username": "<your username>", "password": "<your password>"}'
curl -b cookies.txt "http://localhost:8000/api/v1/projects/status?workspace=/data/workspaces/test"
```

The last call will 404 (`workspace_not_found`) until a workspace actually exists under `./data/workspaces/` on your machine — that's expected; it confirms auth and the `LEDGERLY_WORKSPACE_ROOT` containment are both working before you deploy anything.

## Deploy

The exact deploy command depends entirely on your own tooling. In general, whatever you use needs to be told:

- The Compose file: `docker-compose.yml` at the repo root.
- The `.env` file with your real `LEDGERLY_API_USERNAME`/`LEDGERLY_API_PASSWORD` (never commit it).
- The source directory (this repo), if your tooling builds the image itself rather than pulling from a registry.
- Port `8000` (the container's `EXPOSE`d port) and `/health` as the health-check path (`ledgerly/api/routers/health.py` — deliberately has no workspace or auth dependency, so the health check must keep working regardless of login state).

If you use a self-hosted deploy tool of your own (a sibling project, a script, a PaaS CLI), that tool's own docs cover its specific flags — nothing about this repo requires a particular one.

## Set Up a Workspace Per Research Project

The mounted volume (`./data/workspaces` locally, `/data/workspaces` inside the container, matching `LEDGERLY_WORKSPACE_ROOT`) is empty on first deploy. Each research project gets its own workspace folder underneath it, exactly like local CLI use — deployment doesn't change how workspaces work, only where they live.

`POST /api/v1/projects/init` takes the same fields as CLI `init`, so a workspace can be created over the wire via `curl`/the API directly instead of needing shell access to the host:

```bash
curl -b cookies.txt -X POST https://your-deployed-domain.example/api/v1/projects/init \
  -H "Content-Type: application/json" \
  -d '{
    "workspace": "/data/workspaces/my-thesis",
    "project_name": "My Thesis",
    "project_type": "PhD",
    "topic": "..."
  }'
```

Because `LEDGERLY_WORKSPACE_ROOT=/data/workspaces` is set, subsequent calls can reference this workspace as `workspace=my-thesis` (relative to the root) instead of repeating the full absolute path.

## Update

Rebuild the image from updated source and restart the container in place, using whatever mechanism you deployed with (`docker compose up --build -d`, or your own tooling's update/redeploy command). This is not zero-downtime blue/green — expect a brief restart.

Session cookies issued before an update will be invalidated (the in-memory session store does not survive a restart, by design — see the Dockerfile's single-process note); anyone using the API will need to log in again after an update.

## Rollback

There's no built-in rollback. If a deploy goes wrong: fix the issue in this repo, commit, and redeploy the fixed code. The workspace data volume (`./data/workspaces` on the host) is untouched by any of this — a bad deploy cannot lose research data, only the running service.

## License and Developer Information Consistency

This repo's `README.md` and `LICENSE` state the license terms and contact information for the project. Once deployed, the web UI's About/License footer modal (`ledgerly/web/templates/index.html`) should keep showing the same notice — it's sourced from `LICENSE`/`README.md` already, so keep them in sync if either changes. There is nothing on the API itself (`GET /health`, JSON responses) that needs a license notice — that only matters once there's an actual page for a human to load, which the web UI now provides.

## Keeping Your Own Deployment Notes

This file is meant to be generic — usable by anyone who clones this repo, regardless of what domain or hosting they use. If you want to keep a runbook with your own real domain, host details, or deploy-tool invocation, put it in a gitignored file (e.g. `docs/DEPLOY.personal.md`, already excluded via `.gitignore`) rather than editing this one, so personal infrastructure details don't end up in a repo meant to be generically useful.
