# Arc → Zen Migration Guide

> Created: 2026-03-08
> Status: Ready to execute when you're ready

---

## Your 4 Arc Spaces → Zen Workspaces

Create these in Zen: **Settings → Workspaces**

| Workspace | Colour suggestion | Key pinned tabs |
|-----------|-------------------|-----------------|
| **Favourites** | Green | Dashboard, Readwise, Guardian, NYT, Letterboxd, Trakt, FPL |
| **Shopping** | Orange | HotUKDeals, LatestDeals, Depop, eBay, Vinted, Marrkt |
| **RAI** | Blue | Shift72, Google Sheets/Forms, Gmail (RAI), SharePoint, Trello |
| **Misc** | Purple | Therapy bookmarks, personal |

---

## Bookmark Folders to Create (per Workspace)

### Favourites
- **Jobs** — LinkedIn jobs, Netflix/Disney/BFI/Channel 4 careers pages
- **Vintage Clothing** — Olderbest, workwear/linen/canvas pieces

### Shopping
- **Holiday** — Jet2Holidays, HolidayPirates shortlists
- **Clothing → Suits** — Corneliani/Todd Snyder pieces
- **Shoe Storage** — Warehouse shortlist
- **Birthday** — Miansai, Alice Made This, Hatton Labs, JAM Homemade
- **Underbed Storage** — Wham/WOPPLXY shortlist

### RAI
- **RAI Film Festival** — Shift72 Admin, Film Metadata sheet, Gmail (RAI), Dropbox
- **RoyalAI SharePoint** — Film Live Documents, Film Live Home
- **RAI Film** — Trello, WordPress admin (2019 + 2023 festivals)

### Misc
- **Therapy** — Zoe Hedderly, Laura Rader, Andrea Christelis, Choose Therapy
- **pn** — personal bookmarks

---

## Extensions to Install

Go to **addons.mozilla.org** and install these.

### Install these first (core)
- [ ] uBlock Origin — `addons.mozilla.org/en-GB/firefox/addon/ublock-origin/`
- [ ] Dark Reader — `addons.mozilla.org/en-GB/firefox/addon/darkreader/`
- [ ] Kagi Search — `addons.mozilla.org/en-GB/firefox/addon/kagi-search-for-firefox/`
- [ ] Freedom — `addons.mozilla.org/en-GB/firefox/addon/freedom-website-blocker/`
- [ ] Grammarly — `addons.mozilla.org/en-GB/firefox/addon/grammarly-1/`
- [ ] Raycast Companion — `addons.mozilla.org/en-GB/firefox/addon/raycast-companion/`

### Install these next (productivity)
- [ ] ActivityWatch Web Watcher — `addons.mozilla.org/en-GB/firefox/addon/aw-watcher-web/`
- [ ] Raindrop.io — `addons.mozilla.org/en-GB/firefox/addon/raindropio/`
- [ ] Readwise Highlighter — `addons.mozilla.org/en-GB/firefox/addon/readwise-highlighter/`
- [ ] Refined GitHub — `addons.mozilla.org/en-GB/firefox/addon/refined-github-/`
- [ ] Zotero Connector — `addons.mozilla.org/en-GB/firefox/addon/zotero-connector/`
- [ ] Pieces for Developers — `addons.mozilla.org/en-GB/firefox/addon/pieces-copilot/`
- [ ] Toolkit for YNAB — `addons.mozilla.org/en-GB/firefox/addon/toolkit-for-ynab/`
- [ ] News Feed Eradicator — `addons.mozilla.org/en-GB/firefox/addon/news-feed-eradicator/`
- [ ] Unpaywall — `addons.mozilla.org/en-GB/firefox/addon/unpaywall/`
- [ ] Wikiwand — `addons.mozilla.org/en-GB/firefox/addon/wikiwand-wikipedia-modernized/`

### Media / streaming
- [ ] Enhancer for Netflix — `addons.mozilla.org/en-GB/firefox/addon/enhancer-for-netflix/`
- [ ] Plexboxd — search Firefox addons for "plexboxd"
- [ ] Nikflix (Netflix bypass) — search Firefox addons
- [ ] Letterboxd Extras — search Firefox addons

### Style
- [ ] Stylus (replaces Stylebot) — `addons.mozilla.org/en-GB/firefox/addon/styl-us/`

### Skip — built into Firefox/Zen or already removed
- ~~Picture-in-Picture~~ → built in (right-click any video)
- ~~Reader Mode~~ → built in (icon in address bar) — *also removed from Arc*
- ~~Screen Shader~~ → use macOS Night Shift or f.lux instead
- ~~Google Docs Dark Mode~~ → Dark Reader handles this — *also removed from Arc*
- ~~Download Manager~~ → built in — *also removed from Arc*
- ~~Enhanced GitHub~~ → Refined GitHub replaces it — *also removed from Arc*
- ~~Pause / Limit / Centered / Focus / Insight~~ → Freedom handles this — *all removed from Arc*
- ~~OpenVideo~~ → uBlock Origin handles this — *removed from Arc*
- ~~OxaPay~~ → not needed — *removed from Arc*
- ~~Internet Archive Downloader~~ → use the website directly — *removed from Arc*
- ~~Medium Pro~~ → Arc reader mode handles this — *removed from Arc*
- ~~Vendoo Crosslist~~ → keeping Crosslist Magic only — *removed from Arc*

### Chrome-only (no Firefox equivalent — keep Arc for these)
- Crosslist Magic (Depop/eBay cross-listing)
- MYO Studio / Yoto MYO Magic
- Gixen eBay Sniper → check gixen.com for a Firefox version

---

## One-Time Setup Steps

1. **Set Kagi as default search** — after installing the Kagi extension, go to Firefox Settings → Search → set Kagi as default
2. **Export Arc bookmarks** — Arc menu → File → Export Bookmarks → import into Firefox
3. **DEVONthink clipper** — open DEVONthink 3 → Preferences → Install Browser Extension (has a Firefox version)
4. **Set Zen as default browser** — System Preferences → Desktop & Dock → Default web browser → Zen
5. **Import passwords** — Arc uses the system keychain; Zen/Firefox will prompt on first visit to each site, or import via 1Password extension

---

## After Migration

Once Zen is your primary browser and you've been using it for a week:
- Quit Arc
- Wait another week to make sure nothing is missing
- Then: delete `~/Library/Application Support/Arc/` → **frees 5.1GB**

---

## Notes

- Arc still receives **security + Chromium updates** despite being sunsetted — no rush to delete it immediately
- Zen is Firefox-based: uBlock Origin works *better* in Firefox than Chrome
- If Dia browser gets Spaces (expected mid-2026), it may become a better long-term choice since it's Chromium-based and keeps all your Chrome extensions
