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
