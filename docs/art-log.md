# Art log

Every image John makes in ChatGPT from our prompts gets one row in `art/log.csv`. Claude fills in
every column; John sends the image in the project thread with a 1–5 score and a few words.
The art workflow itself is in the project folder: `context/art-workflow.md` and
`context/prompt-playbook.md`.

## IDs
`<design>-r<round>-<variant>`, e.g. `limit-r02-B`: the "Papa Caught His Limit" mug, round 2, prompt B.
A redo of B in the same round is `limit-r02-B2`, then `B3`; its parent is filled in automatically.
A new round that builds on an earlier image sets `--parent`, e.g. `--parent style-r01-A`.

Design names so far: `style` (round 1 style test), `limit` (Papa Caught His Limit mug),
`recipe` (Nana's Recipe Card), `trophy` (Papa's Trophy Wall).

## Where things live
| What | Where |
|---|---|
| Log | `art/log.csv` (this repo) |
| Prompts, one file per ID | `art/prompts/<id>.md` (this repo; git keeps every version) |
| Images, checks, edge sheets, mug proofs | project folder `designs/<design>/round-NN/` (private; never in this public repo) |

## Columns
`id, date, design, round, variant, parent_id, model, prompt_file, references, image_file, width, height,
transparent, edges_ok, check_notes, john_score, john_notes, decision`

- `model`: what made the image, e.g. "ChatGPT Images".
- `width` … `check_notes`: from the image checker (`designs/tools/study.py` → `<id>_check.json`).
- `decision`: waiting (no image yet, or not scored), keep, revise, drop, approved.

## Commands
```
python3 -m dbc art-log add limit-r02-B --prompt art/prompts/limit-r02-B.md        # when the prompt goes out
python3 -m dbc art-log add limit-r02-B --image designs/limit/round-02/limit-r02-B.png --check limit-r02-B_check.json
python3 -m dbc art-log set limit-r02-B score=4 notes="love the colors" decision=keep
python3 -m dbc art-log show
```

## John's Google Sheet
In the "Dinner Bell Co themes" sheet, add a tab called **Art log** and type this in cell A1:
```
=IMPORTDATA("https://raw.githubusercontent.com/JMar323/dinner-bell-co/main/art/log.csv")
```
It's read-only and Google refreshes it about every hour. Changes reach it once they're merged to main.
