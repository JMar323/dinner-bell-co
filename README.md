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

## Banned terms

The master list is `/mnt/project-files/training/keywords/banned_terms.txt` in the Claude project.
`data/banned_terms.txt` is a copy; a test fails when the two differ (where the project folder is mounted).

## Development

Python 3.11+, no runtime dependencies.

```
pip install pytest
python -m pytest -q
```
