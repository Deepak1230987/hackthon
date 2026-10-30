# Haq: Deployment

**Related documents:** [High-level design](HLD.md) · [Low-level design](LLD.md) · [Implementation plan](IMPLEMENTATION_PLAN.md)

## Backend on the Mumbai VM

Point a DNS `A` record at the VM, open ports 80 and 443, and install Docker. Then:

```sh
git clone https://github.com/Deepak1230987/hackthon.git haq && cd haq
cp .env.example .env     # fill it in; set API_DOMAIN to the hostname and
                         # ALLOWED_ORIGINS to the Vercel URL
docker compose up -d --build
curl https://<hostname>/v1/health
```

Caddy gets the HTTPS certificate on its first request. To update, run `git pull && docker compose up -d --build`.

`backend/pyproject.toml` must list dependencies under `[project].dependencies`, and `app.main:create_app` must exist, for the image to build and start.

## Frontend on Vercel

Import the repository, set **Root Directory** to `frontend`, and set `NEXT_PUBLIC_API_URL` to the backend's public URL with no trailing slash. Pushes to `main` then deploy automatically.

The URL is inlined at build time, so changing it requires a redeploy. Add each new Vercel URL to `ALLOWED_ORIGINS`, including any preview URL you plan to use.

## Check it works

1. `curl -N https://<hostname>/v1/runs/<run_id>/events` prints events as they happen, not all at once.
2. Upload a real PDF from the Vercel URL and watch the live trace.
3. Refresh the page mid-run. The trace must come back and continue.

## Laptop standby

Rehearse this before judging. It uses the same Compose file and database.

1. In `.env`, set `API_DOMAIN=:80`, then run `docker compose up -d --build`.
2. Run a tunnel to `localhost:80`, such as `cloudflared tunnel --url http://localhost:80`.
3. Set `NEXT_PUBLIC_API_URL` on Vercel to the tunnel URL and redeploy.
