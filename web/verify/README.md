# Browser verification

`browser-check.mjs` drives real Chromium against a **built and served** site — not a dev server and
not jsdom — because the things it checks only exist in a browser: layout at a given width, whether
the page scrolls sideways, and whether anything reaches the network.

## Running it

```bash
npm run build
npx vite preview --port 4173 --host 127.0.0.1 --strictPort   # in one terminal
npm run verify:browser -- http://127.0.0.1:4173              # in another
```

Screenshots land in `verify/screenshots/` — one per viewport at load, and one after interacting.

## What it checks, and why

| Check | Why it is here |
| --- | --- |
| Mobile 390×844, tablet 820×1180, desktop 1440×900 | The three widths E0-S7 must work at. Phone access over the LAN is the point of `vite --host` |
| No horizontal page scroll | The most common responsive failure, and invisible in a unit test |
| Nothing escapes the viewport **outside a scroller** | A wide table inside its own `overflow-x: auto` is the intended pattern; an element escaping with no scroller above it is a bug |
| Eleven starters, four substitutes | The squad is the deliverable. A pitch that renders ten players is wrong in a way that reads as fine |
| `±` appears with expected points | Invariant 6 — a mean is never shown without its uncertainty |
| Filter, search, sort, select | E0-S7 requires all of it client-side |
| Sorting **inverts** when toggled | Weaker checks pass by accident: the most expensive player is also the highest scoring, so changing the sort *column* leaves the top row unchanged. Toggling direction is the check that cannot pass by luck |
| No page reload during interaction | `performance` navigation entries stay at 1 |
| **No external network requests** | Invariant 8 / DL-03: the browser reads published static artefacts and calls no API. This is the only place that can actually be observed |
