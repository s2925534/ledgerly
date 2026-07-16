# Corroborly

Placeholder company site scaffold for `corroborly.com` — the evidence/claim-corroboration research tool discussed as a separate product from the `zqx.io` (Zero Queue Exchange) logistics project. Structure mirrors `../zqx` (`apps/site` placeholder pattern, deploy workflow, docker-compose) so the same NAS/Traefik/Cloudflare Tunnel deployment approach can be reused once wired up.

## What's here

- `apps/site/` — Next.js "under construction" placeholder, same stack/style/theme-toggle/health-check pattern as `zqx`'s site.
- `.github/workflows/deploy-site.yml` — build-and-push-to-GHCR workflow, mirroring `zqx`'s.

## What's NOT done yet (needs manual action, not something achievable via available tooling)

1. **`corroborly.com` is not registered.** Confirmed available via authoritative whois as of 2026-07-16 (~$10.44/yr through Cloudflare Registrar, at-cost with no markup). Registration requires a payment method on the Cloudflare account — that step has to happen in the Cloudflare dashboard directly (`domains.cloudflare.com`), there's no API/tool access available here to complete a purchase on your behalf.
2. **DNS/Cloudflare Tunnel routing isn't configured.** Once registered (or once existing DNS is moved to Cloudflare nameservers), a Tunnel route needs to be added pointing `corroborly.com` at the NAS, matching the `zqx.io` / `systemsnotsilos.com` pattern.
3. **GHCR namespace is a placeholder.** `docker-compose.yml` and the workflow currently push to `ghcr.io/s2925534/corroborly-site` (Pedro's personal GitHub account, inferred from other repos) — swap this for a dedicated org (like `zqxio` was created for `zqx`) if this product should ship under its own GitHub org.
4. **No self-hosted GitHub Actions runner wired to this repo yet** — the `deploy` job assumes one, same as `zqx`'s.
5. **`npm install` / build has not been verified locally** — this machine has Node 18 installed; the site's `package.json` pins Next.js 16.2.10, which needs Node 20+. The Dockerfile already targets `node:20-alpine`, so the Docker build path is unaffected, but local `npm run dev` won't work here without a Node 20 upgrade (e.g. via `nvm`).

Once 1–4 are done, pushing to `main` should deploy this exactly the way `zqx.io` deploys today.
