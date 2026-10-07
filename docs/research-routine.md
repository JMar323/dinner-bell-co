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
2. **Themes.** If `config/research.toml` has `[themes] sheet_csv_url`, read John's sheet. This
   container can't reach Google from the shell, so:
   - `python3 -m dbc themes` prints the sheet's CSV link.
   - Read it with the Google Drive connector if it's connected, otherwise WebFetch that link. Google
     answers with a redirect to a googleusercontent.com address: WebFetch that one too, asking for
     "the full CSV text verbatim, every row, nothing else".
   - Save it as `/mnt/project-files/research/weekly/<week>/themes.csv`, then run
     `python3 -m dbc themes --themes <that file>`. It fails if the CSV came back mangled (no `theme`
     column) and lists rows that are new, turned off or changed compared with `config/themes.csv`.
     If it fails twice, use `config/themes.csv` and say so in the reply.
   - Pass `--themes <that file>` to the next two commands, and put the changes in the reply.
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
7. **Lingo.** If the report has a "LINGO FOR THE THEMES SHEET" section, add one short line to the
   reply per theme with new terms, and say the cells are in `report.md` for John to paste into the
   sheet's `lingo` column. When John OKs them, copy the same cells into `config/themes.csv` in a PR so
   the backup matches.

## Niche lingo

The themes sheet's `lingo` column holds the words the gift's recipient really uses: for Fishing,
"hawg (a big bass); honey hole (a secret spot); skunked (caught nothing all day)". Terms are split by
`;` with an optional meaning in brackets. It's context only: the brief gives it to the research so
the ideas sound like they come from inside the hobby, and the art prompts can borrow it to describe
a scene ("a hefty bucketmouth bass bursting up through lily pads"). It's never pasted into a design
or a listing as a list, and every term is screened against `data/banned_terms.txt` (blocked ones are
dropped, and ones already in the sheet are flagged to remove).

Each week, themes with fewer than `[lingo] min_terms` terms (`config/research.toml`) get up to
`new_terms` more researched with sources, so a new row fills itself in. `python3 -m dbc themes --lingo`
prints every theme's lingo for writing prompts.

## When John picks

For each idea he keeps: write `ideas/<id>.toml` in the drafter's format (see
`ideas/papas-keepers-mug.toml`), run `python3 -m dbc draft ideas/<id>.toml`, fix anything the
checks fail, and open one PR with the idea files and drafts. Add his likes and dislikes to
`ideas/feedback.md` in the same PR. Products without a listing template yet (hoodie, hat) need
specs and John's price first: ask him. Nothing is created in Printify or Etsy.
