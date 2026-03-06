# Letterboxd / Plex Integration Status

**Checked on:** 2026-02-17

## EmBoxd (computer-geek64/emboxd)

- Repo README still lists Plex as planned support (`Plex #6`), not shipped.
- Issue `#6` ("Support Plex media server") is still **open**.
- Latest release (`v0.1.2`, published 2025-12-15) only lists Letterboxd automation bugfixes, no Plex feature delivery.

Conclusion: EmBoxd is not yet a reliable Plex path as of 2026-02-17.

## Practical Alternatives

- `treysu/letterboxd-plex-sync`:
  - One-way sync from Letterboxd -> Plex.
  - Supports watched status, ratings, and watchlist.
- `brege/plex-letterboxd`:
  - Exporter from Plex -> Letterboxd import CSV.
  - Good for backfilling watch history into Letterboxd.

## Recommendation

- If priority is **Letterboxd -> Plex ongoing sync**, trial `treysu/letterboxd-plex-sync`.
- If priority is **Plex history -> Letterboxd backfill**, use `brege/plex-letterboxd` first.
- Re-check EmBoxd issue #6 before migration decisions.
