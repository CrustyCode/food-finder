Update food_price_comparison.csv in this repository with current UK supermarket prices.

Most of the work is done by a script. Your job is to run it, then fill only the cells it could not reach. Do not re-fetch anything the script already got.

STEP 1 - Run the scraper.

    python3 update_prices.py

It reads sources.csv, scrapes trolley.co.uk and Ocado product pages, normalises every price to £ per kilogram (or £ per litre for milk and other drinks), rewrites food_price_comparison.csv, and writes gaps.txt. Read its output. It prints one line per source it resolved and lists any source that yielded nothing.

Before rewriting anything it copies last week's food_price_comparison.csv to food_price_comparison_prev.csv. The dashboard reads both files and works out what moved, so that snapshot is what the summary at the top of the page — and every per-price percentage on it — is measured against. Two consequences:

- Run the script once. A second run in the same session would overwrite the snapshot with this week's own figures and flatten every percentage on the page to zero.
- Never hand-edit food_price_comparison_prev.csv. It is last week's committed file and nothing else.

STEP 2 - Read gaps.txt. It names the exact item/supermarket cells that have no price. That list is your entire remaining workload. Do not look up any cell that is not in it, and do not look up Aldi, Lidl, Iceland or Co-op at all — those are scrape-only by design.

STEP 3 - Fill the gaps with WebSearch and WebFetch.

Work item by item. For each missing cell find the supermarket's current price for that product, divide by the pack weight to get £ per kilogram (or by the volume in litres for drinks), and write the result into food_price_comparison.csv as a plain decimal with two places, no pound sign, e.g. 2.50.

ORGANIC RULE (strict): if the item name contains the word "Organic", only a certified organic product counts. A non-organic alternative is never acceptable — leave the cell empty instead. For items without "Organic" in the name, any reasonable equivalent is fine.

Leave a cell empty if the supermarket genuinely does not stock a match. An empty cell is a correct answer; a guessed or stale number is not. Never carry forward last week's figure to fill a blank.

Known constraints, so you do not waste attempts:
- Tesco, Sainsbury's and ASDA return 403 to scripted requests. Use WebFetch for these, not Bash or curl.
- M&S renders prices in the browser, so its prices never appear in raw HTML. WebFetch is the only route.
- Ocado and trolley.co.uk are already handled by the script. Only investigate them by hand if gaps.txt still lists them.

STEP 4 - Feed what you learned back into sources.csv, so the cell is free next week.

Whenever you find a price on a page that publishes schema.org product data, append a row to sources.csv:

    item,url,store,unit_override

Set `store` to the CSV column the price belongs to (e.g. `Ocado`). Leave `unit_override` empty unless the page gives a count rather than a weight — e.g. a 6-pack of apples — in which case put the pack weight there, e.g. `750g`. For trolley.co.uk product pages leave `store` empty; one such page can carry several supermarkets at once.

Do not add trolley.co.uk /search/ URLs — their robots.txt disallows that path. Only /product/ pages.

Before adding a row, sanity-check it is a like-for-like product. A premium or flavoured variant will make that supermarket look wrongly expensive; leave the cell for next time rather than adding a bad match.

STEP 5 - Check the Unit column and recalculate Cheapest.

The Unit column says what every price in that row is measured in — `kg` for solids, `l` for milk and other drinks. The script fills it from what it scraped. Make sure the prices you added use that same unit; a row mixing £/kg and £/litre is meaningless. If a row's Unit is empty because the script scraped nothing for it, set it yourself to whichever unit you used.

Then recalculate the Cheapest column for every row: the supermarket with the lowest non-empty price. If several tie, join them with a forward slash, e.g. Ocado/ASDA. The script already does this for the cells it filled, so redo it after your edits.

STEP 6 - Sanity check before committing. Diff food_price_comparison.csv against food_price_comparison_prev.csv — that pair is exactly what the dashboard compares — and investigate anything that moved more than about 30% either way. That usually means a product page changed to a different pack size, not a real price change, and it would otherwise be published as a headline price crash at the top of the page. Fix the source or empty the cell rather than let a bad figure through.

Look too at what the summary will lead with: the biggest changes in each item's *cheapest* price, which is what the page ranks its movers by. Anything past about 10% deserves a second look at the product page behind it. Report anything you could not resolve.

STEP 7 - Commit all changed files, including sources.csv and food_price_comparison_prev.csv, with the message:

    chore: weekly price update YYYY-MM-DD

using today's date. Then push it to master explicitly:

    git push origin HEAD:master

That explicit push is the only thing that lands the update. The runner makes its own push to a derived branch named `master-<random>`, which nothing deploys from — `session_context.outcomes` sets the base branch to check out, not the push target, so this cannot be fixed by configuration. Only the repository's default branch can deploy to GitHub Pages.

If the push is rejected as non-fast-forward, master moved while you were working. Report that and stop. Never use --force.
