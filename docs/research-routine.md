# Weekly idea research as a Claude routine

John's choice for routine 1 if it runs on his Claude plan (no API key). The routine fires every
Monday morning into the "Weekly idea research" thread of the Etsy project. This file is the
routine's standing instruction; the routine prompt just says "do this week's research per
docs/research-routine.md". Change the steps here, not in the routine.

The Python side is the same one the API engine uses, so both produce the same report:
`dbc research-brief` (instructions + answer format) and `dbc research-ingest` (scores, screens
banned and franchise terms, writes report.md + ideas.json).

## Each Monday

1. `cd` to the repo and `git pull` the default branch.
2. **Themes.** If `config/research.toml` has `[themes] sheet_csv_url`, read John's sheet (the Google
   Drive connector if it's connected, otherwise WebFetch the CSV link) and save it, same columns, as
   `/mnt/project-files/research/weekly/<week>/themes.csv`. Pass it to the next two commands with
   `--themes <that file>`. Mention new or changed rows in the reply.
3. `python3 -m dbc research-brief --inbox /mnt/project-files/research/weekly` (plus `--themes`) and follow the brief
   exactly: web research (WebSearch, WebFetch), 15 ideas, scores with evidence, sources you read,
   no listing fields unless the brief asks.
4. Save the answer as JSON matching the schema the brief prints, to
   `/mnt/project-files/research/weekly/<week>/answer.json`.
5. `python3 -m dbc research-ingest /mnt/project-files/research/weekly/<week>/answer.json --inbox /mnt/project-files/research/weekly` (plus `--themes`).
   It fails loudly on a malformed answer: fix the JSON and run it again.
6. Reply in the thread with the week's summary and the numbered list (name, score, product, one
   line why), attach `report.md` and `ideas.json`, and ask John which numbers to move forward.
   Blocked ideas stay listed with the reason.

## When John picks

For each idea he keeps: write `ideas/<id>.toml` in the drafter's format (see
`ideas/papas-keepers-mug.toml`), run `python3 -m dbc draft ideas/<id>.toml`, fix anything the
checks fail, and open one PR with the idea files and drafts. Add his likes and dislikes to
`ideas/feedback.md` in the same PR. Products without a listing template yet (hoodie, hat) need
specs and John's price first: ask him. Nothing is created in Printify or Etsy.
