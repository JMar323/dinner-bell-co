# Dinner Bell Co automation

Tools for the Dinner Bell Co Etsy shop (personalized family gifts, printed by Printify).
Plan and routines: [docs/plan.md](docs/plan.md). API keys: [docs/keys.md](docs/keys.md).
Everything runs from n8n on the VPS, which calls these Python commands: [deploy/n8n.md](deploy/n8n.md).

**Approval rules:** nothing here publishes a listing, sends an order to production or changes
a price. John approves every design, listing, price change and bulk action. New listings ramp
at 5 a day for the first 30 days.

## Listing drafter

One idea file in, a listing draft out:

```
python -m dbc draft ideas/papas-keepers-mug.toml
```

writes `drafts/papas-keepers-mug.json` and `drafts/papas-keepers-mug.md` and prints the checks.
After hand-editing a draft's JSON, re-check it with `python -m dbc check drafts/<id>.json`.
Exit code 1 means a check failed.

Automatic checks:
- title under 15 words and at most 140 characters, no quotes, no stray spaces, only characters
  Etsy accepts, `% : & +` once each; holiday words and repeated "gift" are warnings
- exactly 13 unique tags, each 20 characters or less, Etsy tag characters only
- every term in `data/banned_terms.txt` (block = fail, caution = warning, per product type)
- never the word "gang" anywhere (say crew or buddies)
- both disclosures in the description (AI use and production partner Printify), the returns
  promise, and the Christmas order-by date until it passes
- production partner exactly "Printify"; prices not yet approved by John are warnings
- personalization: at most 5 fields, questions 45 characters, instructions 120 characters

Idea file fields are documented in `ideas/papas-keepers-mug.toml` (full) and
`ideas/nana-est-crewneck.toml` (minimal; the drafter builds the title and fills the tags).

## Order watcher

```
python -m dbc printify-check          # token works? which Printify shop gets watched?
python -m dbc --json watch-orders     # what n8n runs every 30 minutes
python -m dbc watch-orders --dry-run  # see what it would email, without remembering it
```

Reads Printify orders and emails (through n8n) each new held order once, a reminder for any order
still on hold after 18 hours, and any order that has issues, is unfulfillable, has a payment
problem or was canceled. It never approves, sends to production, cancels or edits an order: the
Printify client only sends GET requests. Keys come from `~/.config/dinnerbellco/.env` or `/etc/dinnerbellco/.env` (docs/keys.md);
what was already emailed is kept in `$DBC_STATE_DIR/watch-orders.json`. Settings live in
`config/shop.toml` under `[orders]`.

## Nightly update

```
python -m dbc update --dry-run        # what would the nightly update pull?
python -m dbc --json update           # what n8n runs at 3:15am: fast-forward only, then a drafter smoke test
```

Never overwrites edits or commits made on the server; it emails what to do instead.

## Weekly idea research

```
python -m dbc research-brief                    # this week's instructions + answer format (any engine)
python -m dbc research-ingest answer.json       # score, screen, write ideas/inbox/<week>/report.md
python -m dbc --json research                   # the whole run through the Anthropic API (needs a key)
python -m dbc research-check                    # does the key work? (free)
```

Themes come from `config/themes.csv` or John's Google Sheet with the same columns; settings in
`config/research.toml`; John's likes and no-gos in `ideas/feedback.md`. 15 ideas a week, scored on
demand, competition and gift fit with sources; banned and franchise terms are blocked. John picks,
then listings are written. As a Claude routine (no key): [docs/research-routine.md](docs/research-routine.md).

## Art log

```
python -m dbc art-log add limit-r02-B --prompt art/prompts/limit-r02-B.md   # one row per image John makes
python -m dbc art-log set limit-r02-B score=4 decision=keep                 # his score and the decision
python -m dbc art-log show
```

`art/log.csv` tracks prompt, model, image, checks and John's score for every art image; prompts are in
`art/prompts/`, images stay in the private project folder. John's sheet shows the log with IMPORTDATA:
[docs/art-log.md](docs/art-log.md).

## Banned terms

The master list is `/mnt/project-files/training/keywords/banned_terms.txt` in the Claude project.
`data/banned_terms.txt` is a copy; a test fails when the two differ (where the project folder is mounted).

## Development

Python 3.10+, no runtime dependencies (Python 3.10 uses the TOML reader copied into `dbc/_vendor/`).

```
pip install pytest
python -m pytest -q
```
