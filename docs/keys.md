# API keys: what to create and where they live

Rule: keys go into your password manager and the server's `.env` file only.
Never into chat, the repo, GitHub issues, or /mnt/project-files.

## Where to store them

1. **Master copy:** your password manager, one entry per key.
2. **Working copy:** on the VPS at `/etc/dinnerbellco/.env`, readable only by the user n8n runs
   as (`chmod 600`). The Python commands read it at start-up, so the keys never pass through n8n
   workflow fields or its execution logs. `.env.example` in the repo lists the variable names with
   no values.
3. **Email login:** in n8n's own credential store (Credentials → SMTP or Gmail), not in `.env`.

## Keys to create

| # | Key | Create it when | Where | Settings | Variable names |
|---|---|---|---|---|---|
| 1 | **Printify personal access token** | Now | Printify → avatar → My Profile → Connections → API tokens → Generate (printify.com/app/account/api) | Name it `dinnerbellco-vps`. Tick only: shops.read, orders.read, products.read, catalog.read, webhooks.read/write. Add orders.write later (stage 2 auto-approval), uploads.write + products.write later (publish step). Shown once; valid 1 year, so set a reminder for Oct 2027 | `PRINTIFY_TOKEN` |
| 2 | **Etsy Seller App** (Seller API access) | After the shop is open: Etsy only grants it to "an active Etsy shop in good standing" | etsy.com/developers → apply for Seller API access (two-field form, approved in minutes). Then etsy.com/developers/your-apps shows the keystring and shared secret | Callback URL: `https://<your-vps-domain>/etsy/callback` (exact match, case-sensitive). Scopes requested at login: `transactions_r listings_r shops_r`; `listings_w` only later for tag/title edits you approve | `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET` |
| 3 | **Etsy refresh token** | Right after #2 | Not created by hand: you run a one-time login on the VPS (`python -m dbc etsy-login`, coming with the Etsy step) and approve in the browser | Access tokens last 1 hour and refresh themselves; the refresh token lasts 90 days and renews on every run. If nothing runs for 90 days, log in again | `ETSY_REFRESH_TOKEN` (written by the script) |
| 4 | **Email for alerts** | Before the order watcher goes live | In n8n: Credentials → New → SMTP (with an app password from Google Workspace: Security → App passwords) or Gmail OAuth2 | Send to the address you check daily. Swapping to Google Chat or Slack later is a node change in n8n, no code | none in `.env` (n8n credential) |
| 5 | **GitHub deploy key** for the VPS | When we install on the VPS | Run `ssh-keygen -t ed25519 -f ~/.ssh/dinnerbellco` on the VPS as the n8n user, then GitHub repo → Settings → Deploy keys → add the `.pub` file | Tick "Allow write access" so the stats and research jobs can commit their files | none (SSH key file) |
| 6 | **Anthropic API key** for the weekly idea research | Before routine 1 is built | console.anthropic.com → Settings → API keys → Create key; set a monthly spend limit there | Name it `dinnerbellco-research` | `ANTHROPIC_API_KEY` |

Not needed: a Printify OAuth app (that's for multi-merchant apps), Etsy commercial access (requests for it have triggered automatic bans).

Later, only for stage 2: a Printify webhook secret (a random string you generate) as `PRINTIFY_WEBHOOK_SECRET`.

## Put the Printify token on the VPS

The token goes from Printify into your password manager, and from there straight into a file on
the VPS that only the n8n user can read. It never goes into chat, an n8n node, the repo or a
shell command line (where it would land in your shell history).

**1. Create the token in Printify** (key #1 above)

1. Printify → your avatar (top right) → **My Profile** → **Connections**, or go straight to
   printify.com/app/account/api.
2. **Generate** a personal access token. Name: `dinnerbellco-vps`.
3. Scopes: tick only **shops.read, orders.read, products.read, catalog.read, webhooks.read,
   webhooks.write**. Leave every other write scope off.
4. Copy the token **once** into a new password-manager entry "Printify API token (dinnerbellco-vps)"
   with today's date. Printify won't show it again. It lasts 1 year: add a reminder for early
   October 2027.

**2. Create the secrets file and state folder** (SSH into the VPS; `N8NUSER` is the user n8n runs
as, see [deploy/n8n.md](../deploy/n8n.md) step 1; with Docker and the custom image use `1000`)

```
sudo install -d -m 700 -o N8NUSER /etc/dinnerbellco
sudo install -m 600 -o N8NUSER /opt/dinner-bell-co/.env.example /etc/dinnerbellco/.env
sudo install -d -m 700 -o N8NUSER /var/lib/dinnerbellco
```

**3. Paste the token into the file**

```
sudo -u N8NUSER nano /etc/dinnerbellco/.env
```

- On the `PRINTIFY_TOKEN=` line, paste the token right after the `=` (no spaces, no quotes).
- Fill in `ALERT_EMAIL_TO=` (where alerts go) and `ALERT_EMAIL_FROM=` (the address your n8n SMTP
  credential sends as). Leave `DBC_STATE_DIR=/var/lib/dinnerbellco` as it is.
- Save with Ctrl+O, Enter, then exit with Ctrl+X.

**4. Check it works without showing it**

```
cd /opt/dinner-bell-co && sudo -u N8NUSER python3 -m dbc printify-check
```

Expected: `token works; 1 shop(s) in Printify` (or 0 before you connect Etsy) and a line saying
which shop the watcher uses. The token itself is never printed. `401` means it was mistyped or
revoked: generate a new one and paste it again. Then run the **setup-check** workflow in n8n
(deploy/n8n.md step 7) to confirm n8n sees it too.

**If the token ever leaks** (pasted somewhere it shouldn't be): delete it in Printify →
Connections straight away, generate a new one and repeat step 3.
