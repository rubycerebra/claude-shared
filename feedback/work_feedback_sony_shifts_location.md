---
name: Sony shifts location and tooling
description: Where Sony shift data lives, the rate, and how to manage it — prevents blanking on "sony shifts" references
type: reference
originSessionId: b8c6bdcf-fd71-4f4f-86f2-2419a2480fcc
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_sony_shifts_location.md
  migrated_on: 2026-05-17
---
Sony shifts are tracked **separately** from work-projects.json (which is Atomic Film only).

- **Data file:** `~/Documents/Finance/Sony/sony-shifts.json`
- **Rate:** £35/hr
- **CLI:** `WORK/.helpers/sony_cli.py` — commands: `add`, `tbd`, `list`, `week`, `submit`, `submit-all`, `edit`
- **Edit a shift:** `python3 .helpers/sony_cli.py edit <shift-id> <start> <end>` e.g. `edit sony-2026-05-01 09:00 13:00`
- **Monthly income view (Sony + Atomic Film combined):** `python3 .helpers/income.py`
