# Weekly price routine

Cloud routine `trig_01PBrJJTdi9KF8HokdB9BjRj` — "Weekly UK Supermarket Price
Update", `0 2 * * 4` (Thursdays 03:00 BST). Manage it at
<https://claude.ai/code/routines>.

`prompt-current.md` is what the routine runs today. `prompt-2026-03.md` is the
original browse-everything version, kept so the change can be reverted.

## Why it changed

The original prompt asked the agent to WebSearch and WebFetch a price for every
item at every supermarket — about 154 lookups a week, rediscovering the same
product pages from scratch each time, pulling 150–200KB of JS-heavy retailer
DOM into context for each one. Cost grew quadratically as one context
accumulated every page.

Now `update_prices.py` scrapes what can be scraped (~41 cells) for almost no
context, writes `gaps.txt`, and the agent only chases what is left.

## What the routine must know

- It pushes to a `claude/*` branch, **not** master, regardless of what the
  prompt says — `job_config.ccr.session_context.outcomes` pins the branch.
  `.github/workflows/deploy.yml` handles that and syncs the CSV back to master.
- Tesco, Sainsbury's and ASDA return 403 to scripted requests; M&S renders
  prices client-side. Those cells can only be filled with WebFetch/WebSearch.
- Ocado and trolley.co.uk scrape cleanly and are already wired into
  `sources.csv`. Never add a `/search/` URL for trolley — their robots.txt
  disallows it. Product pages are fine.
