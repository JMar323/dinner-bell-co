# Running the Python commands from n8n on the VPS

n8n owns the schedules and the alert channel; this repo owns the logic. Every routine is:

```
Schedule Trigger → Execute Command: python3 -m dbc --json <command> → Code node → Send Email
```

With `--json`, each command prints one JSON object and exits 0, so a failed check or a Printify
outage shows up as `"ok": false` (and, for the watcher, a ready-made error email) instead of
crashing the n8n execution. A real crash (bad config, missing file, `ALERT_EMAIL_TO` not set)
exits non-zero, the Execute Command node fails, and the error workflow emails John.

The commands read their keys from `/etc/dinnerbellco/.env` themselves, so no key ever sits in a
workflow field or an n8n execution log.

## Workflows in `n8n/`

| File | What it does | Trigger |
|---|---|---|
| `setup-check.json` | Runs the drafter on the Papa's Keepers idea, `printify-check` and a dry run of the watcher, and shows PASS/FAIL for each | Manual ("Test workflow") |
| `order-watcher.json` | `dbc watch-orders`: new held orders, 18-hour reminders, has-issues / unfulfillable / payment / canceled. Emails only when there's something new | Every 30 min, 7:00am–9:30pm Eastern |
| `error-alert.json` | Emails John when any routine crashes | n8n Error Trigger |

The watcher is read-only: the Printify client can only send GET requests, and a test fails if
anyone adds a way to approve, send or cancel an order.

## One-time setup (native n8n: installed with npm or as a system service)

1. **Find the user n8n runs as:** `ps -o user= -p $(pgrep -f "n8n start" | head -1)` (often `n8n` or
   your own login). Commands below call it `N8NUSER`.
2. **Get the code** (as that user): `sudo -u N8NUSER git clone https://github.com/JMar323/dinner-bell-co.git /opt/dinner-bell-co`
   (create `/opt/dinner-bell-co` owned by N8NUSER first if needed). The repo is public, so no
   deploy key is needed to read it. Check `python3 --version` is 3.11 or newer.
3. **Secrets file and state folder:** follow [docs/keys.md → Put the Printify token on the VPS](../docs/keys.md#put-the-printify-token-on-the-vps).
4. **Enable the Execute Command node.** n8n 2.x blocks it by default. Add `NODES_EXCLUDE="[]"`
   to n8n's environment (systemd: `sudo systemctl edit n8n`, add `Environment=NODES_EXCLUDE=[]`
   under `[Service]`; pm2/.env: add the line) and restart n8n. Anyone who can edit workflows can
   then run shell commands as N8NUSER, so keep n8n's login behind 2FA.
5. **Email credential:** n8n → Credentials → New → SMTP (Google Workspace: smtp.gmail.com, port 465,
   SSL on, your address, an app password from Google Account → Security → App passwords).
6. **Import the workflows:** n8n → Workflows → Add workflow → ⋯ → Import from file, once per file in
   `n8n/`. In each Send Email node pick the SMTP credential. In **error-alert**, replace both
   `CHANGE-ME@example.com` with your address. Then open **order-watcher** → ⋯ → Settings →
   Error workflow → "Dinner Bell Co: error alert" → Save.
7. **Smoke test:** open **setup-check** and click Test workflow. Expected:
   - Drafter: PASS, with one warning (mug care specs to confirm).
   - Printify token: PASS with your shop list, or FAIL "PRINTIFY_TOKEN is not set" until the token is in.
   - Order watcher (dry run): `ok: true` and the note "no Etsy-connected shop in Printify yet" until
     the shop opens and Printify is connected.
8. **Turn on the watcher:** toggle **order-watcher** to Active. It stays quiet until there's an
   order, apart from one email if Printify can't be reached.

## If n8n runs in Docker

The official `n8nio/n8n` image has no Python, and the container can't see `/opt` or `/etc` on the
host. Two ways round it; pick one when we know your setup:

- **SSH node (recommended for Docker):** keep the Python on the host and swap each Execute Command
  node for n8n's SSH node ("Execute a command") pointed at the host (`172.17.0.1`, a dedicated
  low-privilege user, key login). No custom image, and the Execute Command node stays blocked.
- **Custom image:** `FROM n8nio/n8n:<your version>`, `USER root`, `RUN apk add --no-cache python3`,
  `USER node`; mount `-v /opt/dinner-bell-co:/opt/dinner-bell-co:ro -v /etc/dinnerbellco:/etc/dinnerbellco:ro
  -v /var/lib/dinnerbellco:/var/lib/dinnerbellco`, and make the files readable by uid 1000 (the
  container's `node` user). Then steps 4–8 above apply unchanged.

## Updating

`cd /opt/dinner-bell-co && git pull` (an n8n workflow can do this nightly). Re-import a workflow
from `n8n/` only when its file changes; the commands themselves update with the pull.
