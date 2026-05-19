---
name: feedback-filebot-dedup
description: Never add regex-based filename dedup to media organise scripts — the broken approach wiped ~18GB on 2026-05-15
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 55404b21-c01f-4cb9-8a6e-1a457ccb3b73
  project: TODO
  source_file: feedback_filebot_dedup.md
  migrated_on: 2026-05-17
---

Do NOT add regex-based filename normalisation as a basis for destructive dedup in the `radarr-organise.ps1` script (or any media organise script).

**Why:** On 2026-05-15 a dedup function in `C:\FileBot\radarr-organise.ps1` used the regex `\.[^.]+$` to strip trailing dotted segments. This treated *the first dot inside the title* (Mr., Dr., A.P., U.S.) as a file extension, so every title starting with "Mr.", "Dr.", "A.P." etc. normalised to the same group key. The script then hard-deleted (`Remove-Item -Force`, no Recycle Bin) all but the largest "duplicate" in each group, destroying ~18GB of completely distinct media. Recovered all but Mr. Arkadin (1955) via Radarr/Sonarr re-search.

**How to apply:**
- FileBot's `--conflict skip` already handles real duplicates safely on rename — no separate dedup needed.
- Radarr/Sonarr have their own duplicate detection on import.
- If a user explicitly asks for dedup, use exact byte-for-byte hash comparison (SHA-256), never regex-normalised filenames.
- Any automated delete on shared media MUST use Recycle Bin (no `-Force`), or stage to a quarantine folder first.

**Other lessons from the same incident:**
- The script also lacked `-r` on FileBot calls and used `--filter "f.isFile()"` which incorrectly filtered TMDB match candidates. Now uses `-r` + no filter.
- FileBot move passes should set `--output $dir` to keep renames in-place. Cross-drive `--output F:\Movies` from D:\Complete\Movies counts as moving files between drives — Jim explicitly does not want this; Radarr/Sonarr handle library imports.

See [[memory:user_career_history]] and project state on 2026-05-15.
