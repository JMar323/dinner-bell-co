# Running the Python commands from n8n on the VPS

n8n owns the schedules and the alert channel; this repo owns the logic. Every routine is:

```
Schedule Trigger → Execute Command: python3 -m dbc --json <command> → Code/IF node reads "ok" → Send Email
```

With `--json`, each command prints one JSON object and exits 0, so a failed check shows up as
`"ok": false` instead of crashing the n8n execution. A real crash (bad config, missing file) still
exits non-zero, and n8n's error workflow should email John.

## One-time setup

1. **Get the code on the VPS** (as the user n8n runs as):
   `git clone git@github.com:JMar323/dinner-bell-co.git /opt/dinner-bell-co` (uses the deploy key in docs/keys.md #5).
   Python 3.11 or newer is the only requirement (`python3 --version`).
2. **Secrets file:** create `/etc/dinnerbellco/.env` from `.env.example`, `chmod 600`, owned by the n8n user.
   Type the keys in on the server; never paste them into chat or an n8n node.
3. **Enable the Execute Command node.** n8n 2.x blocks it by default. Set `NODES_EXCLUDE="[]"`
   in n8n's environment and restart n8n (docs.n8n.io → Configure n8n → Security → Block specific nodes).
   Only the account that edits workflows can use it, so keep n8n's login behind 2FA.
4. **If n8n runs in Docker**, the container can't see the host's Python or `/opt` by default.
   Either mount the repo and env file into the container and use an image with `python3`
   (e.g. `-v /opt/dinner-bell-co:/opt/dinner-bell-co:ro -v /etc/dinnerbellco:/etc/dinnerbellco:ro`),
   or tell Claude and we'll add a small local HTTP endpoint instead so n8n uses an HTTP Request node.
5. **Smoke test** in an Execute Command node:
   `cd /opt/dinner-bell-co && python3 -m dbc --json draft ideas/papas-keepers-mug.toml --out /tmp/dbc-drafts`
   should return `"ok": true` with one warning (mug care spec to confirm).

## Updating

`cd /opt/dinner-bell-co && git pull` (an n8n workflow can do this nightly). Workflows are exported
to `n8n/` in this repo so they're versioned with the code.
