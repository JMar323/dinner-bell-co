# Running the Python commands from n8n on the VPS

n8n owns the schedules and the alert channel; this repo owns the logic. Every routine is:

```
Schedule Trigger → Execute Command: python3 -m dbc --json <command> → Code node → Send Email
```

With `--json`, each command prints one JSON object and exits 0, so a failed check or a Printify
outage shows up as `"ok": false` (and, for the watcher, a ready-made error email) instead of
crashing the n8n execution. A real crash (bad config, missing file, `ALERT_EMAIL_TO` not set)
exits non-zero, the Execute Command node fails, and the error workflow emails John.

The commands read their keys from `~/.config/dinnerbellco/.env` (or `/etc/dinnerbellco/.env`)
themselves, so no key ever sits in a workflow field or an n8n execution log.

## Workflows in `n8n/`

| File | What it does | Trigger |
|---|---|---|
| `setup-check.json` | Runs the drafter on the Papa's Keepers idea, `printify-check` and a dry run of the watcher, and shows PASS/FAIL for each | Manual ("Test workflow") |
| `order-watcher.json` | `dbc watch-orders`: new held orders, 18-hour reminders, has-issues / unfulfillable / payment / canceled. Emails only when there's something new | Every 30 min, 7:00am–9:30pm Eastern |
| `error-alert.json` | Emails John when any routine crashes | n8n Error Trigger |
| `nightly-update.json` | `dbc update`: fast-forwards `~/dinner-bell-co` to what was merged on GitHub, then runs the drafter once with the new code. Emails only when new code arrived (and names any workflow file to re-import) or when it couldn't update | Every night, 3:15am Eastern |
| `idea-research.json` | `dbc research`: the weekly idea research through the Anthropic API. Only needed if the research runs from n8n instead of as a Claude routine; needs `ANTHROPIC_API_KEY` and the `anthropic` package (docs/keys.md #6) | Mondays, 8am Eastern |

The watcher is read-only: the Printify client can only send GET requests, and a test fails if
anyone adds a way to approve, send or cancel an order.

## One-time setup on John's server (xCloud one-click n8n)

Checked 2026-10-06 from the xCloud terminal: n8n runs natively (`/usr/bin/n8n`, not Docker) as the
user `u1_flow2`, the terminal runs as that same user without sudo, Python is 3.10.12 and git is
installed. So the code and keys live in `u1_flow2`'s home folder and nothing needs sudo.
Python 3.10 works: the repo carries its own copy of the TOML reader that 3.11 has built in.

1. **Code and keys:** in the xCloud terminal, follow [docs/keys.md → Put the Printify token on the VPS](../docs/keys.md#put-the-printify-token-on-the-vps)
   (clone to `~/dinner-bell-co`, keys in `~/.config/dinnerbellco/.env`).
2. **Enable the Execute Command node:** xCloud → your n8n site → **Environment** → add the line
   `NODES_EXCLUDE=[]` → **Save** (n8n restarts). n8n 2.x blocks this node by default. Anyone who can
   log in to n8n can then run commands as `u1_flow2`, so keep n8n's login behind 2FA.
3. **Email credential:** n8n → Credentials → New → SMTP (Google Workspace: smtp.gmail.com, port 465,
   SSL on, your address, an app password from Google Account → Security → App passwords).
4. **Import the workflows:** n8n → Workflows → Add workflow → ⋯ → Import from file, once per file in
   `n8n/` (download them from GitHub or `~/dinner-bell-co/n8n/`). In each Send Email node pick the
   SMTP credential. In **error-alert**, replace both `CHANGE-ME@example.com` with your address. Then
   open **order-watcher** → ⋯ → Settings → Error workflow → "Dinner Bell Co: error alert" → Save.
5. **Smoke test:** open **setup-check** and click Test workflow. Expected:
   - Drafter: PASS, with one warning (mug care specs to confirm).
   - Printify token: PASS with your shop list, or FAIL "PRINTIFY_TOKEN is not set" until the token is in.
   - Order watcher (dry run): `ok: true` and the note "no Etsy-connected shop in Printify yet" until
     the shop opens and Printify is connected.
6. **Turn on the watcher:** toggle **order-watcher** to Active. It stays quiet until there's an
   order, apart from one email if Printify can't be reached.

On another server with sudo the same steps work with the code anywhere (change the `cd ~/dinner-bell-co`
in each Execute Command node) and the keys in `/etc/dinnerbellco/.env`.

## If n8n runs in Docker

The official `n8nio/n8n` image has no Python, and the container can't see the host's files.
Two ways round it:

- **SSH node (recommended for Docker):** keep the Python on the host and swap each Execute Command
  node for n8n's SSH node ("Execute a command") pointed at the host (`172.17.0.1`, a dedicated
  low-privilege user, key login). No custom image, and the Execute Command node stays blocked.
- **Custom image:** `FROM n8nio/n8n:<your version>`, `USER root`, `RUN apk add --no-cache python3`,
  `USER node`; mount the repo at `/home/node/dinner-bell-co` and the keys at
  `/home/node/.config/dinnerbellco`, readable by uid 1000 (the container's `node` user), and set
  `DBC_STATE_DIR` to a writable mounted folder. Then steps 2–6 above apply unchanged.

## Updating

The **nightly-update** workflow does `git pull` for you: every night at 3:15am Eastern it fetches
GitHub and fast-forwards `~/dinner-bell-co` to the merged code. It never overwrites anything:

- Files edited on the server, or commits made on the server, stop the update and you get an email
  saying which files and the one command that fixes it.
- After an update it runs the drafter once with the new code. If that fails you get an email with the
  command that puts the old version back.
- When a file in `n8n/` changed, the email names it: re-import that workflow (Workflows → Import from
  file, replace the old one, pick the email credential, turn it back on). Python changes need nothing.
- Nothing new means no email.

Set it up once: Workflows → Import from file → `n8n/nightly-update.json` → pick the SMTP credential in
**Email John** → ⋯ → Settings → Error workflow → "Dinner Bell Co: error alert" → Save → toggle Active.
Try it now with **Test workflow**: with nothing new it stops after "Anything to email?" (no email).

By hand at any time: `cd ~/dinner-bell-co && python3 -m dbc update --dry-run` shows what would change.
The repo is public, so the server needs no GitHub key to pull. If it ever goes private, add a
read-only deploy key (docs/keys.md #5) and switch the remote to SSH.
