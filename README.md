# admin-feed

A public feed of admin-surface changes on major protocols across Ethereum, Arbitrum, Optimism and Base: timelock schedules and executions, proxy upgrades, role grants and revokes, Safe signer and threshold changes, and queued Safe transactions before they execute.

Live page: https://imal1ice.github.io/admin-feed/ · RSS: https://imal1ice.github.io/admin-feed/feed.xml

It is [ownerwatch](https://github.com/imal1ice/ownerwatch) running `run --once` every hour on a free GitHub Actions runner against Tenderly's public gateways, which were cross-checked against the official RPCs for completeness (one popular public RPC silently drops logs; details in the ownerwatch README). The config is `ownerwatch.yaml`; the cursor state and every alert (`alerts.jsonl`) are committed back by the workflow, so the whole history is in this repo. `build.py` renders the page and the feed from the JSON lines, standard library only.

Watched today: Uniswap, Compound, Aave (governance on all four chains), Arbitrum DAO (L1 and L2 timelocks, governors, Security Council), ENS, Lido, Morpho (Ethereum and Base), the Optimism Foundation Safe and the Optimism L2 ProxyAdmin. Suggestions for contracts to add are welcome as issues; the bar is "a change here matters to many depositors".

Delay is up to an hour because of the cron. For alerts within a block, run ownerwatch yourself, or ask about hosting.

Nothing here is a judgement about any project. Alerts are produced from public chain data and reflect what the contracts did, not whether it was a good idea.
