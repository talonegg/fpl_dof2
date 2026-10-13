# fpl_dof2

**FPL DOF** — a decision-support platform for Fantasy Premier League: optimal squad selection,
weekly transfer recommendations, and a player scouting UI, built to run at zero cost.

Planning is baselined. Implementation starts with a **steel thread to the GW1 deadline**
(Fri 21 Aug 2026, 18:30 BST) — a thin but complete path through every architectural layer.

- [Implementation plan](docs/planning/epics/README.md) — the plan of record
- [Full planning set](docs/planning/README.md) — charter, architecture, conceptual design, decision log

No secrets in this repository, ever. It is public, and API keys live only in GitHub Actions secrets.

## Password gate

The web app asks for a password before it renders anything or fetches `data/v1`. The password itself is never stored anywhere: the build gets its SHA-256 hash from the repository secret `FPL_PASSWORD_HASH`, which `deploy.yml` passes in as `VITE_FPL_PASSWORD_HASH`.

To set or change the password:

1. Compute the hash. `printf` avoids a trailing newline, which would change the hash:

   ```sh
   printf '%s' 'yourpassword' | sha256sum | cut -d' ' -f1
   ```

2. Store it as the secret, either with the CLI:

   ```sh
   gh secret set FPL_PASSWORD_HASH   # paste the hash when prompted
   ```

   or in **Settings › Secrets and variables › Actions › New repository secret**, named `FPL_PASSWORD_HASH`.

3. **Redeploy.** The hash is fixed into the bundle at build time, so re-run the Deploy workflow (or wait for the next pipeline-triggered deploy). After that, every browser that unlocked with the old password is locked again.

If the secret is missing or empty, the build still runs, but `deploy.yml` logs a warning and the site shows **"Site locked: password not configured"** without ever rendering the app.

Use the **Lock** button in the top bar to sign out on a shared device.

> **Deterrence only.** This is a client-side check on a static site. `data/v1/*.json` and the JS bundle (which contains the hash) can still be fetched directly by anyone who knows the URLs, and a weak password can be brute-forced offline from the hash. Do not put anything here that must stay secret.
