# Weekly price routine

Cloud routine `trig_01PBrJJTdi9KF8HokdB9BjRj` — "Weekly UK Supermarket Price
Update", `0 2 * * 4` (Thursdays 03:00 BST). Manage it at
<https://claude.ai/code/routines>.

`prompt-current.md` is a copy of what the routine runs. `prompt-2026-03.md` is
the original browse-everything version, kept so the change can be reverted.

## Editing these files changes nothing

The prompt the routine actually executes is stored server-side on the trigger.
Nothing syncs it to this directory, in either direction, so the two drift
silently — the routine keeps firing successfully on whatever it was last given.
On 2026-08-04 the stored prompt was still the March version, three months and
one refactor out of date, having run weekly the whole time.

After editing `prompt-current.md`, push it with the `RemoteTrigger` tool:

    {action: "update", trigger_id: "trig_01PBrJJTdi9KF8HokdB9BjRj",
     body: {job_config: {ccr: {...}}}}

Send the whole `job_config` back with only
`events[0].data.message.content` changed. A body carrying just the parts you
edited risks dropping `session_context.outcomes`, which is the only thing
pinning the push branch. Read the current config first with
`{action: "get", trigger_id: "..."}` and edit that.

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
- `update_prices.py` fetches from Bash, so it needs the sandbox to allow egress
  to `www.trolley.co.uk` and `www.ocado.com`. That allowlist comes from two
  different places, which is what made the failure confusing:
  - **On a developer's machine**, from the `WebFetch(domain:…)` permission
    rules — Claude Code derives the sandbox allowlist from them. These now live
    in the tracked `.claude/settings.json`; `.gitignore` used to exclude the
    whole of `.claude/`, so a fresh clone had no egress at all.
  - **In the cloud routine**, from the environment's own network access
    settings (`env_011CUqCa5jqSbAostLeufsv1`, edit at
    <https://claude.ai/code>). Repository settings do not reach it. Any new
    scrape host must be added there as well, or the routine silently reaches
    nothing while it works fine locally.

  WebFetch and WebSearch are in-process and bypass the sandbox entirely, which
  is why hand-filling gaps kept working throughout.
- Tesco, Sainsbury's and ASDA return 403 to scripted requests; M&S renders
  prices client-side. Those cells can only be filled with WebFetch/WebSearch.
- Ocado and trolley.co.uk scrape cleanly and are already wired into
  `sources.csv`. Never add a `/search/` URL for trolley — their robots.txt
  disallows it. Product pages are fine.
