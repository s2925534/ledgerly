# Corroborly Site

Barebones placeholder company site for corroborly.com. Next.js (App Router, TypeScript), no database, no CMS. Structure and tooling mirror `../zqx/apps/site` (same Next.js/React versions, same dark/light/system theme toggle pattern, same health-check contract) for consistency across Pedro's projects.

## Develop

```bash
npm install
npm run dev
```

## Build

```bash
npm run build
npm start
```

## Deploy

Intended pattern (mirrors `zqx`'s `deploy-site.yml` + `synology-site-deployer`, not yet wired up for this repo):

1. GitHub Actions builds and pushes to `ghcr.io/s2925534/corroborly-site` on every push to `main` touching this directory — adjust the GHCR namespace in `docker-compose.yml` and the workflow if this ships under a dedicated GitHub org instead (as `zqx` did with `zqxio`).
2. A self-hosted runner calls `synology-site update corroborly.com --health-path /health --container-name corroborly-site` to pull the new image on the NAS.
3. `corroborly.com` needs to be registered and its DNS moved to Cloudflare (nameservers or a Cloudflare-managed zone) before a Cloudflare Tunnel route can be added, matching how `zqx.io` and `systemsnotsilos.com` are fronted (`Cloudflare edge → Tunnel(veloso-nas) → NAS Traefik → this container`).

None of the above is live yet — this is the code/config scaffold only. See `../../README.md` for what's outstanding.

Health check: `GET /health` returns `200 ok`.
