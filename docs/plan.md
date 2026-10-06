# Dinner Bell Co automation: layout and routines

Status: 2026-10-06 (Workstream 5, updated for the nightly update and idea research). John's answers: every routine runs on the **n8n instance on
his VPS**; n8n schedules the work and calls the Python code here; alerts go by **email** for now
(Google Chat or Slack later is just a different n8n node). Nothing publishes, orders or changes a
price without John's OK.

How n8n calls Python: a Schedule Trigger, then an **Execute Command** node running
`python3 -m dbc --json <command>`, which prints one JSON object. n8n parses it and decides what to
send (Send Email node). Python holds the business logic and the tests; n8n holds the schedule and
the alert channel. Setup details: [deploy/n8n.md](../deploy/n8n.md).

## Repo layout

```
dinner-bell-co/
├── README.md              how to run it, approval rules
├── pyproject.toml         Python 3.10+, no runtime dependencies
├── .env.example           the name of every secret, never a value
├── config/
│   ├── shop.toml          shop facts, both disclosures, promise, holiday order-by date
│   ├── research.toml      idea research: how many ideas, products, focus, scoring
│   ├── themes.csv         the themes to research (or John's Google Sheet, same columns)
│   └── products.toml      mug / tee / crewneck specs, price + approval status
├── data/
│   └── banned_terms.txt   copy of /mnt/project-files/training/keywords/banned_terms.txt
├── ideas/                 one .toml per kept idea (drafter input); feedback.md = John's notes for research
├── drafts/                drafter output: <id>.json (machine) + <id>.md (for John)
├── dbc/
│   ├── drafter.py         idea -> title, 13 tags, description, personalization   [built]
│   ├── checks.py          automatic listing checks                                [built]
│   ├── banned.py          banned/caution term matcher                             [built]
│   ├── cli.py             python -m dbc draft | check | printify-check | watch-orders |
│   │                      update | research | research-brief | research-ingest     [built]
│   ├── printify.py        Printify API client (read-only, GET only)               [built]
│   ├── etsy.py            Etsy OAuth (PKCE) + receipts/listings                   [next]
│   ├── watcher.py         held-order watcher (emails via n8n)                     [built]
│   ├── research.py        weekly idea research: brief, scoring, IP screen, report [built]
│   ├── updater.py         nightly fast-forward to what was merged on GitHub       [built]
│   └── stats.py           weekly stats pull                                       [next]
├── deploy/n8n.md          how n8n on the VPS runs the Python commands
├── n8n/                   exported n8n workflows: order watcher, error alert, setup check,
│                          nightly update, idea research (API engine)                  [built]
├── docs/                  this plan, keys.md
└── tests/                 pytest; CI runs them on every push
```

## The first four routines

| # | Routine | n8n schedule | What the Python command does | Approval gate |
|---|---|---|---|---|
| 1 | **Weekly idea research** | Mondays | John's themes sheet (any theme he adds; franchises only "in spirit", never by name), his notes in `ideas/feedback.md`, the ideas he kept and recent weeks' lists go into `dbc research-brief`. The research engine searches the web and returns 15 ideas scored on demand, competition and gift fit with cited sources; `dbc research-ingest` scores them, blocks banned and franchise terms, and writes the report. Engine: a Claude routine on John's plan (no key, docs/research-routine.md) or `dbc research` from n8n with an API key | John picks ideas by number. Only then are listings written (into `ideas/`, by PR) and art made |
| 2 | **Listing drafter** | On demand, and inside routine 1 | `dbc draft` (built): one idea in; title, 13 tags, description, personalization fields, settings and a check report out | A draft is only a file. Publishing is a later step that needs John's OK per listing, max 5 new listings a day for the first 30 days |
| 3 | **Order watcher** | Every 30 min, 7am–10pm | `dbc watch-orders` reads Printify orders (read-only) and returns new held orders ("Review needed" / on-hold) with the Etsy receipt number, items and, once the Etsy app exists, the buyer's personalization text; plus 18-hour reminders (we promise a 1-day review) and has-issues, unfulfillable or payment problems. n8n emails each one once | Never sends anything to production. John approves in Printify. Auto-approval with spot checks (stage 2) only after ~20 orders/month and John's OK |
| 4 | **Weekly stats report** | Mondays 6am | `dbc stats` pulls Etsy listings (views, favorites) and last week's receipts plus Printify order costs; computes revenue, cost, fees and margin per listing; appends `data/stats/<year>-W<week>.csv`; flags listings to retire (no sales after 60–90 days) or clone, and feeds winners into routine 1. n8n emails the report | Report only. Any price change or bulk edit is a suggestion for John |

Keys live in one file on the VPS that the Python commands read; the email login lives in n8n's
own credential store. See [keys.md](keys.md).

## Build order

1. Listing drafter + checks + banned terms (done 2026-10-06).
2. Printify client + order watcher + its n8n workflow (built 2026-10-06; goes live once the Printify token is on the VPS).
3. Etsy app + OAuth, then personalization text in the watcher (needs the shop open first).
4. Weekly stats (needs the Etsy app and a few weeks of listings).
5. Weekly idea research (built 2026-10-06: themes sheet, brief, scoring and screening, report; runs as a Claude routine or from n8n).
   Nightly update (built 2026-10-06): n8n fast-forwards the server to merged code every night.
6. Later: publish step (Printify product from an approved draft), stage-2 order auto-approval.

## Art phase deadline (Christmas cutoff Tue Dec 8)

Critical path for the first product, worst case, in business days:
art + John's OK + USPTO check (5) → Printify template + longest-name test (1) →
sample mug production 1–3 + shipping 2–5 (8) → photo, hand-made listing, open the shop,
connect Printify, publish the Printify version (2). About 16 business days, skipping
Veterans Day (Nov 11) and Thanksgiving (Nov 26).

| Start art | Shop opens about | What it buys |
|---|---|---|
| **Mon Oct 26 (recommended)** | Tue Nov 17 | Three weeks of selling, including the mid-November search peak and Cyber 5 (Nov 26–30) |
| **Mon Nov 2 (latest worth doing)** | Tue Nov 24 | Open just before Thanksgiving and Cyber 5; about two weeks of sales before Dec 8 |
| Fri Nov 13 (absolute floor) | Mon Dec 7 | Open one day before the cutoff; almost no Christmas sales |

New listings take 60–90 days to rank on their own (research/niches.md), so a Christmas launch
leans on Etsy Ads whichever date is picked. Recheck Printify's 2026 cutoffs in early November.
