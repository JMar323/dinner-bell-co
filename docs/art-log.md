# Art log

Every image John makes in ChatGPT from our prompts gets one row in `art/log.csv`.

**John's part:** paste the prompt into ChatGPT, post the image in the project thread, and say keep,
redo or drop (or nothing, and Claude suggests one). No IDs, no scores: Claude names every image and
fills in every column. The workflow itself is in the project folder: `context/art-workflow.md` and
`context/prompt-playbook.md`.

## IDs (Claude's)
`<design>-r<round>-<variant>`, e.g. `limit-r02-B`: the "Papa Caught His Limit" mug, round 2, prompt B.
A redo of B is `limit-r02-B2`, then `B3`; its parent is filled in automatically. A new round that
builds on an earlier image sets `--parent`, e.g. `--parent style-r01-A`.

## Where things live
| What | Where |
|---|---|
| Log | `art/log.csv` (this repo) |
| Prompts, one file per ID | `art/prompts/<id>.md` (this repo; git keeps every version) |
| Images, checks, mug proofs | project folder `designs/<design>/round-NN/` (private; never in this public repo) |

## Columns
`id, date, design, parent_id, prompt_file, image_file, check, notes, decision`

- `check`: "ok" or "problem", the pixel size, and anything the image checker flagged
  (`designs/tools/study.py` → `<id>_check.json`).
- `notes`: what John said, or what Claude saw.
- `decision`: keep, redo, drop, or blank while undecided.

## Commands
```
python3 -m dbc art-log add limit-r02-B --prompt art/prompts/limit-r02-B.md        # when the prompt goes out
python3 -m dbc art-log add limit-r02-B --image designs/limit/round-02/limit-r02-B.png --check limit-r02-B_check.json
python3 -m dbc art-log set limit-r02-B decision=keep notes="love the colors"
python3 -m dbc art-log show
```

## John's Google Sheet
In the "Dinner Bell Co themes" sheet, add a tab called **Art log** and type this in cell A1:
```
=IMPORTDATA("https://raw.githubusercontent.com/JMar323/dinner-bell-co/main/art/log.csv")
```
It's read-only and Google refreshes it about every hour. Changes reach it once they're merged to main.
