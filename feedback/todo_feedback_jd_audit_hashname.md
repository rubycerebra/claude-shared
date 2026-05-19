---
name: feedback-jd-audit-hashname
description: "When auditing JDownloader packages against Radarr, match on file URL/name inside the package, not just the RL- prefix slug — hash-named packages will false-flag as orphan"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e8083b60-fe51-40d4-9f27-f91af5c6326e
  project: TODO
  source_file: feedback_jd_audit_hashname.md
  migrated_on: 2026-05-17
---

When auditing JDownloader2 packages against Radarr (e.g. `RL-*` packages on NUC `localhost:3128/downloadsV2/queryPackages`), do **not** rely solely on matching the package name to a Radarr title.

Hash-style names like `RL-9135645f51d0` will look orphan-by-name but the actual file inside (queried via `downloadsV2/queryLinks` with `packageUUIDs`) reveals what it actually is. On 2026-05-15 the package `RL-9135645f51d0` was flagged as "no Radarr lookup match" but its single link was `Clash.By.Night.1952.mkv` — i.e. Clash by Night, already imported by Radarr and moved to `F:\Movies`.

**Why:** rarelust / FlashGot pushes packages with name=`RL-<short_id>` where the short_id is a content hash, not a slug. Most packages get a slug-style name but a fraction don't, and those will always look orphaned to a name-only audit.

**How to apply:** Any JD audit logic must query links inside a flagged package before declaring it orphan. The check is:
```
POST /downloadsV2/queryLinks  params=[{packageUUIDs:[<uuid>], name:true, url:true}]
```
Use the link `name` (e.g. `Clash.By.Night.1952.mkv`) and/or the parent dir under `saveTo` to confirm whether it corresponds to a real Radarr film before flagging.

Related: [[user_role]]
