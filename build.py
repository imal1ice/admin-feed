"""Render docs/index.html and docs/feed.xml from alerts.jsonl. Standard library only."""
from __future__ import annotations

import collections
import datetime as dt
import html
import http.client
import json
import pathlib
import re
import shutil
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).parent
ALERTS = ROOT / "alerts.jsonl"
DOCS = ROOT / "docs"
SITE = "https://imal1ice.github.io/admin-feed/"
EXPLORERS = {"ethereum": "https://etherscan.io", "base": "https://basescan.org",
             "arbitrum": "https://arbiscan.io", "optimism": "https://optimistic.etherscan.io"}
SAFE_PREFIXES = {"ethereum": "eth", "base": "base", "arbitrum": "arb1", "optimism": "oeth"}
MAX_PAGE = 500

ICON_TAGS = (
    f'<link rel="icon" type="image/png" sizes="180x180" href="{SITE}favicon.png">'
    f'<link rel="apple-touch-icon" href="{SITE}favicon.png">'
    '<meta name="theme-color" content="#121D30">'
)


def head_extra(og_title: str, og_desc: str, og_url: str) -> str:
    """Favicon + Open Graph / Twitter card tags shared by every page."""
    t = html.escape(og_title, quote=True)
    d = html.escape(og_desc, quote=True)
    return (
        ICON_TAGS +
        '<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{t}">'
        f'<meta property="og:description" content="{d}">'
        f'<meta property="og:url" content="{og_url}">'
        f'<meta property="og:image" content="{SITE}og-image.png">'
        '<meta name="twitter:card" content="summary_large_image">'
    )
MAX_RSS = 100
# On-chain text (proposal descriptions, vote metadata) can hold characters XML 1.0 forbids; one of them breaks the whole feed.
XML_ILLEGAL = re.compile("[^\\t\\n\\r\\x20-\\ud7ff\\ue000-\\ufffd\\U00010000-\\U0010ffff]")


def load() -> list[dict]:
    if not ALERTS.exists():
        return []
    rows = [json.loads(l) for l in ALERTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    assign_guids(rows)
    rows.sort(key=lambda r: (r.get("ts", ""), r.get("block", 0)), reverse=True)
    return rows


def assign_guids(rows: list[dict]) -> None:
    """Give each alert a stable RSS guid. Alerts carry no log index and one transaction can emit the same event
    on the same contract many times, so repeats get a counter. rows must be in file order: alerts.jsonl only
    grows, so a counter never changes once assigned."""
    seen: collections.Counter = collections.Counter()
    for r in rows:
        base = f"{r.get('chain')}:{(r.get('tx_hash') or '').rsplit('/', 1)[-1]}:{r.get('contract')}:{r.get('event')}:{r.get('block')}"
        seen[base] += 1
        r["guid"] = base if seen[base] == 1 else f"{base}:{seen[base]}"


def xml_text(value: object) -> str:
    return escape(XML_ILLEGAL.sub("", str(value)))


def tx_url(row: dict) -> str:
    """ownerwatch stores a full explorer URL in tx_hash when explorer_url is configured, else a bare hash."""
    tx = row.get("tx_hash") or ""
    if tx.startswith("http"):
        return tx
    if row.get("source") == "Safe" and not row.get("block"):
        # A queued Safe transaction carries a safeTxHash at block 0: it has no on-chain transaction yet.
        prefix = SAFE_PREFIXES.get(row.get("chain", ""))
        return f"https://app.safe.global/transactions/queue?safe={prefix}:{row.get('contract')}" if prefix else ""
    base = EXPLORERS.get(row.get("chain", ""), "")
    return f"{base}/tx/{tx}" if base and tx.startswith("0x") else ""


def tx_link(row: dict) -> str:
    url = tx_url(row)
    h = (row.get("tx_hash") or "-").rsplit("/", 1)[-1]
    if url:
        return f'<a href="{html.escape(url)}">{html.escape(h[:10])}…</a>'
    return html.escape(h or "-")


def addr_link(row: dict) -> str:
    base = EXPLORERS.get(row.get("chain", ""), "")
    a = row.get("contract", "")
    short = f"{a[:6]}…{a[-4:]}" if a.startswith("0x") and len(a) > 12 else a
    return f'<a href="{base}/address/{html.escape(a)}">{html.escape(short)}</a>' if base and a.startswith("0x") else html.escape(a)


def render_html(rows: list[dict]) -> str:
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_day: dict[str, list[dict]] = {}
    for r in rows[:MAX_PAGE]:
        by_day.setdefault(r.get("ts", "")[:10] or "unknown", []).append(r)
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin surface changes</title>
<link rel="alternate" type="application/rss+xml" title="admin-feed" href="feed.xml">
{head_extra("admin-feed — DeFi admin surface changes", "Timelock queues, upgrades, role grants and Safe changes on major protocols on Ethereum, Arbitrum, Optimism and Base, via ownerwatch.", SITE)}
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e5e5e5;--crit:#b00020;--high:#c2410c;--med:#a16207;--info:#2563eb}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--muted:#999;--line:#2a2a2a;--crit:#ff6b6b;--high:#fb923c;--med:#facc15;--info:#60a5fa}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}} p.sub{{color:var(--muted);margin:0 0 24px}}
h2{{font-size:14px;color:var(--muted);font-weight:600;letter-spacing:.04em;text-transform:uppercase;margin:28px 0 8px}}
.a{{border-top:1px solid var(--line);padding:10px 0}} .a:last-child{{border-bottom:1px solid var(--line)}}
.sev{{font-size:11px;font-weight:700;letter-spacing:.06em;padding:1px 6px;border-radius:4px;color:#fff;margin-right:8px;vertical-align:middle}}
.critical{{background:var(--crit)}} .high{{background:var(--high)}} .medium{{background:var(--med)}} .info{{background:var(--info)}}
.meta{{color:var(--muted);font-size:13px}} .msg{{margin:4px 0 0;word-break:break-word}} a{{color:inherit}} code{{font-size:13px}}
footer{{color:var(--muted);font-size:13px;margin-top:32px}}
</style></head><body>
<h1>Admin surface changes</h1>
<p class="sub">Timelock queues, upgrades, role grants, Safe signer changes and queued Safe transactions on major protocols across Ethereum, Arbitrum, Optimism and Base, as they happen. Polled hourly by <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a> on a free GitHub Actions runner. <a href="report.html">Report: who controls 36 DeFi protocols</a> · <a href="activity.html">Three months of admin activity</a> · <a href="transparency.html">Control surface at a glance</a> · <a href="disclosures.html">Control disclosures</a> · <a href="feed.xml">RSS</a> · <a href="https://github.com/imal1ice/admin-feed">source and config</a> · <a href="work.html">About and contact</a></p>"""]
    if not rows:
        parts.append("<p>No changes recorded yet. The feed started on " + gen + ".</p>")
    for day, items in by_day.items():
        parts.append(f"<h2>{html.escape(day)}</h2>")
        for r in items:
            sev = html.escape(r.get("severity", "info"))
            parts.append(
                f'<div class="a"><span class="sev {sev}">{sev.upper()}</span>'
                f'<strong>{html.escape(r.get("label", ""))}</strong> <span class="meta">{addr_link(r)} · {html.escape(r.get("chain", ""))} · '
                f'{html.escape(r.get("source", ""))}.{html.escape(r.get("event", ""))} · block {r.get("block", "")} · tx {tx_link(r)} · {html.escape(r.get("ts", "")[11:16])} UTC</span>'
                f'<p class="msg">{html.escape(str(r.get("message", "")))}</p></div>')
    parts.append(f"<footer>Generated {gen}. Alerts are produced from public chain data only; nothing here is a judgement about any project. "
                 f"Run it on your own contracts: <code>pip install ownerwatch</code>.</footer></body></html>")
    return "\n".join(parts)


def render_rss(rows: list[dict]) -> str:
    items = []
    for r in rows[:MAX_RSS]:
        ts = r.get("ts", "")
        try:
            pub = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        except ValueError:
            pub = ""
        title = f"[{r.get('severity', 'info').upper()}] {r.get('label', '')}: {r.get('event', '')}"
        link = tx_url(r) or SITE
        items.append(f"<item><title>{xml_text(title)}</title><link>{xml_text(link)}</link><guid isPermaLink=\"false\">{xml_text(r.get('guid', ''))}</guid>"
                     f"<pubDate>{pub}</pubDate><description>{xml_text(r.get('message', ''))} (block {r.get('block')}, {xml_text(r.get('chain'))})</description></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Admin surface changes</title>'
            f'<link>{SITE}</link><description>Timelock queues, upgrades, role grants and Safe changes on major protocols on Ethereum, Arbitrum, Optimism and Base, via ownerwatch.</description>'
            + "".join(items) + "</channel></rss>")


CONTROL = ROOT / "control" / "protocols.json"
BLOCKTIMES = ROOT / "control" / "blocktimes.json"
ETH_RPC = "https://mainnet.gateway.tenderly.co"
WINDOW_DAYS = 90
MAX_RECENT = 10
# Events that change who controls a contract or how: owners, roles, implementations, delays, signers.
CONTROL_EVENTS = {
    "OwnershipTransferred", "OwnershipTransferStarted", "RoleGranted", "RoleRevoked", "RoleAdminChanged",
    "Upgraded", "AdminChanged", "BeaconUpgraded", "MinDelayChange", "NewAdmin", "NewPendingAdmin", "NewDelay",
    "VotingDelaySet", "VotingPeriodSet", "ProposalThresholdSet", "QuorumNumeratorUpdated", "TimelockChange",
    "NewImplementation", "SetApp", "SetPermission", "ChangePermissionManager", "PoolUpdated",
    "PoolConfiguratorUpdated", "ACLAdminUpdated", "ACLManagerUpdated", "PriceOracleUpdated", "AddressSetAsProxy",
    "ExecutorSet", "GuardianUpdated", "SetOwner", "SetCurator", "SetGuardian", "SetTimelock", "SetIsAllocator",
    "AddedOwner", "RemovedOwner", "ChangedThreshold", "EnabledModule", "DisabledModule", "ChangedGuard",
    "ChangedFallbackHandler",
    # ownerwatch 0.8.0: Sky, Lido Dual Governance, Rocket Pool, CoW, Gearbox, 0x Settler
    "LogSetOwner", "LogSetAuthority", "PauseDelaySet", "GovernanceSet", "AdminExecutorSet",
    "AfterSubmitDelaySet", "AfterScheduleDelaySet", "EmergencyGovernanceSet", "EmergencyActivationCommitteeSet",
    "EmergencyExecutionCommitteeSet", "EmergencyProtectionEndDateSet", "EmergencyModeDurationSet",
    "EmergencyModeActivated", "EmergencyModeDeactivated", "ProposerRegistered", "ProposerUnregistered",
    "ProposerExecutorSet", "ResealCommitteeSet", "ResealManagerSet", "TiebreakerCommitteeSet",
    "TiebreakerActivationTimeoutSet", "ProposalsCancellerSet", "ConfigProviderSet", "SealableWithdrawalBlockerAdded",
    "SealableWithdrawalBlockerRemoved", "ContractUpgraded", "ContractAdded", "GuardianChanged", "SolverAdded",
    "SolverRemoved", "ManagerChanged", "ProxyImplementationUpdated", "PausableAdminAdded", "PausableAdminRemoved",
    "UnpausableAdminAdded", "UnpausableAdminRemoved", "Deployed", "Removed", "RemovedAll", "Authorized",
}
# A governance decision taking effect. Counted once per transaction: one proposal emits several of these.
EXECUTION_EVENTS = {"CallExecuted", "ExecuteTransaction", "ProposalExecuted", "ExecuteVote", "PayloadExecuted", "SpellExecuted"}


def block_dates(rows: list[dict]) -> dict[int, str]:
    """Block number -> UTC date, read once over JSON-RPC and cached. Alerts carry the time they were seen,
    which can trail the block by up to an hour; dates here are the block's own. A block the RPC will not
    answer this run falls back to the alert's date and is retried on the next build."""
    import time
    import urllib.request
    cache = {int(k): v for k, v in json.loads(BLOCKTIMES.read_text()).items()} if BLOCKTIMES.exists() else {}
    missing = sorted({r["block"] for r in rows if r["block"]} - cache.keys())
    fetched = 0
    for i in range(0, len(missing), 10):
        body = [{"jsonrpc": "2.0", "id": b, "method": "eth_getBlockByNumber", "params": [hex(b), False]} for b in missing[i:i + 10]]
        req = urllib.request.Request(ETH_RPC, json.dumps(body).encode(), {"Content-Type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    answers = json.loads(resp.read())
                if isinstance(answers, list):   # a rate limit or error answers with a single object
                    break
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(2 ** attempt * 2)
        else:
            break
        for ans in answers:
            if isinstance(ans, dict) and ans.get("result"):
                cache[ans["id"]] = dt.datetime.fromtimestamp(int(ans["result"]["timestamp"], 16), dt.timezone.utc).strftime("%Y-%m-%d")
                fetched += 1
        time.sleep(0.5)
    if fetched:
        BLOCKTIMES.write_text(json.dumps({str(k): cache[k] for k in sorted(cache)}, indent=0))
    return {**{r["block"]: r.get("ts", "")[:10] for r in rows}, **cache}


def control_record(system: dict, rows: list[dict], dates: dict[int, str], cutoff: str, today: str) -> dict:
    """One protocol's entry: control changes and executed governance actions on its governance contracts in
    the last WINDOW_DAYS. Counts of events that happened on-chain, with their dates and transactions; no grade."""
    watched = {c["address"].lower() for c in system["contracts"]}
    # a system can name the one execution event that means its decision took effect (Lido: the timelock, not the vote)
    execution_events = set(system.get("execution_events") or EXECUTION_EVENTS)
    mine = [{**r, "date": dates[r["block"]]} for r in rows
            if r.get("chain") == "ethereum" and r.get("contract", "").lower() in watched and r.get("block") in dates
            and dates[r["block"]] >= cutoff and r.get("event") in CONTROL_EVENTS | execution_events]
    mine.sort(key=lambda r: r["block"], reverse=True)
    changes = [r for r in mine if r["event"] in CONTROL_EVENTS]
    executions = {r.get("tx_hash") for r in mine if r["event"] in execution_events}
    if not system.get("executions", True):
        mine = changes
    contracts = []
    for c in system["contracts"]:
        hits = [r for r in mine if r.get("contract", "").lower() == c["address"].lower()]
        contracts.append({**c, "events": len(hits), "last": hits[0]["date"] if hits else None})
    plural = lambda n, word: f"{n} {word}{'s' if n != 1 else ''}"
    if not system.get("decoded", True):
        value = None
    elif system.get("executions", True):
        value = f"{plural(len(changes), 'control change')} · {plural(len(executions), 'governance execution')} in {WINDOW_DAYS} days"
    else:
        value = f"{plural(len(changes), 'control change')} in {WINDOW_DAYS} days"
    return {
        "name": system["name"], "source": system["source"], "value": value, "note": system.get("note"),
        # The counts are over a rolling window, so they hold as of the build, not as of the last event.
        "updatedAt": today, "lastEvent": mine[0]["date"] if mine else None,
        "controlChanges": len(changes), "governanceExecutions": len(executions),
        "window": {"days": WINDOW_DAYS, "from": cutoff},
        "contracts": contracts,
        "recent": [{"date": r["date"], "label": r.get("label", ""), "event": r["event"],
                    "kind": "control change" if r["event"] in CONTROL_EVENTS else "governance execution",
                    "message": str(r.get("message", "")), "tx": tx_url(r)} for r in mine[:MAX_RECENT]],
    }


def render_control(rows: list[dict]) -> tuple[dict, str]:
    cfg = json.loads(CONTROL.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    watched = {c["address"].lower() for s in cfg["systems"].values() for c in s["contracts"]}
    dates = block_dates([r for r in rows if r.get("chain") == "ethereum" and r.get("contract", "").lower() in watched])
    systems = {k: control_record(v, rows, dates, cutoff, now.strftime("%Y-%m-%d")) for k, v in cfg["systems"].items()}
    protocols = {}
    for pid, sid in cfg["protocols"].items():
        rec = systems[sid]
        protocols[pid] = {**rec, "system": sid, "url": f"{SITE}control/#{sid}"}
    data = {"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "chain": "ethereum", "methodology": f"{SITE}control/methodology.html",
            "protocols": protocols}
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin events by protocol</title>
{head_extra("Admin events by protocol — admin-feed", "Per-protocol timelock, upgrade, role and Safe changes on major DeFi protocols, via ownerwatch.", SITE + "control/")}
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e5e5e5}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--muted:#999;--line:#2a2a2a}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 4px;padding-top:12px;border-top:1px solid var(--line)}}
p.sub,.meta{{color:var(--muted)}} .meta{{font-size:13px}} a{{color:inherit}} code{{font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{text-align:left;padding:4px 8px 4px 0;border-bottom:1px solid var(--line);vertical-align:top}}
.scroll{{overflow-x:auto}}
</style></head><body>
<h1>Admin events by protocol</h1>
<p class="sub">Admin events (timelock queues and executions, upgrades, ownership and role changes, Safe signer and threshold changes) recorded by <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a> on each protocol's governance contracts on Ethereum mainnet, over the last {WINDOW_DAYS} days: control changes, and governance executions counted once per transaction. Routine Safe transactions are not counted. Counts of on-chain events, not a rating. <a href="methodology.html">Methodology</a> · <a href="index.json">JSON</a> · <a href="../">live feed</a></p>"""]
    for sid, rec in systems.items():
        parts.append(f'<h2 id="{html.escape(sid)}">{html.escape(rec["name"])}</h2><p><strong>{html.escape(rec["value"] or "Not counted")}</strong></p>'
                     + (f'<p class="meta">{html.escape(rec["note"])}</p>' if rec["note"] else "") +
                     f'<p class="meta">Contracts from <a href="{html.escape(rec["source"])}">the protocol\'s address registry</a>.</p>'
                     '<div class="scroll"><table><tr><th>Contract</th><th>Type</th><th>Events</th><th>Last</th><th>Watched since</th></tr>')
        for c in rec["contracts"]:
            a = c["address"]
            parts.append(f'<tr><td><a href="https://etherscan.io/address/{a}">{html.escape(c["label"])}</a> <code>{a[:6]}…{a[-4:]}</code></td>'
                         f'<td>{html.escape(c["type"])}</td><td>{c["events"]}</td><td>{c["last"] or "–"}</td><td>{c["since"]}</td></tr>')
        parts.append("</table></div>")
        if rec["recent"]:
            parts.append("<ul>" + "".join(
                f'<li>{e["date"]} · {e["kind"]} · {html.escape(e["label"])}: {html.escape(e["message"])}'
                + (f' (<a href="{html.escape(e["tx"])}">tx</a>)' if e["tx"] else "") + "</li>" for e in rec["recent"]) + "</ul>")
    parts.append(f'<footer class="meta">Generated {data["generated"]}. Public chain data only; nothing here is a judgement about any project.</footer></body></html>')
    return data, "\n".join(parts)


TRANS_CORE = [
    ("Uniswap V3 Factory", "ethereum", "timelock-gated governance", "48h", "not read as upgradeable"),
    ("Compound III (USDC Comet)", "ethereum", "timelock-gated governance", "48h", "yes"),
    ("Compound V2 Comptroller", "ethereum", "timelock-gated governance", "48h", "yes"),
    ("Aave V3 Pool", "ethereum", "timelock-gated governance", "24h", "yes"),
    ("Ethena (USDe)", "ethereum", "timelock-gated governance", "24h", "not read as upgradeable"),
    ("Morpho Blue", "ethereum", "a 6-of-10 Safe", "— (immutable core, no upgrades)", "no"),
]
TRANS_GOV = [  # (protocol, governance timelock delay read on-chain, system id in control/protocols.json)
    ("Aave V3", "24h", "aave-governance-v3"),
    ("Compound", "48h", "compound-governance"),
    ("Euler", "96h", "euler-dao"),
    ("Fluid", "24h", "fluid-governance"),
    ("Gearbox", "36h", "gearbox-dao"),
    ("Pendle", "48h", "pendle-governance"),
    ("Uniswap", "48h", "uniswap-governance"),
]
TRANS_ASOF = "2026-11-10"  # date the on-chain facts (delays, upgradeability) were read

TRANS_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DeFi control surface, at a glance</title>
<link rel="icon" type="image/png" href="favicon.png">
<meta name="description" content="A neutral, chain-read reference: for each protocol, what on-chain state says about how its contracts can be changed — timelock, upgradeability, controller, and the last admin change observed live. By ownerwatch.">
<meta property="og:type" content="website">
<meta property="og:title" content="DeFi control surface, at a glance">
<meta property="og:description" content="A neutral, chain-read reference to how DeFi protocols' contracts can be changed: timelock, upgradeability, controller, last change observed. By ownerwatch.">
<meta property="og:url" content="https://imal1ice.github.io/admin-feed/transparency.html">
<meta property="og:image" content="https://imal1ice.github.io/admin-feed/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e5e5e5}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--muted:#999;--line:#2a2a2a}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px} p.sub{color:var(--muted);margin:0 0 20px}
h2{font-size:14px;color:var(--muted);font-weight:600;letter-spacing:.04em;text-transform:uppercase;margin:28px 0 8px}
a{color:inherit} code{font-size:13px}
blockquote{border-left:3px solid var(--line);margin:16px 0;padding:4px 0 4px 14px;color:var(--muted);font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0} td,th{text-align:left;padding:6px 10px 6px 0;border-bottom:1px solid var(--line);vertical-align:top} th{color:var(--muted);font-weight:600}
footer{color:var(--muted);font-size:13px;margin-top:32px}
</style></head><body>
<h1>DeFi control surface, at a glance</h1>
<p class="sub"><a href="./">admin-feed</a> · a neutral chain-read reference by <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a></p>

<p>A neutral, chain-read reference: for each protocol, what on-chain state says about <strong>how its contracts can be changed</strong> — whether changes pass through a timelock, whether the contract is upgradeable, what kind of address controls it, and when its admin surface last changed. Generated with <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a>.</p>

<blockquote><strong>Chain view, not a verdict.</strong> This shows what contract state says, not whether a setup is safe or risky. An address is not how its key is held (an externally-owned account may be a hardware or MPC wallet; a multisig's signers may be one organisation). A blank cell means <em>this read did not resolve that fact from this entry point</em> — never that the fact is absent. This is a neutral public-good reference, not a ranking or a judgment of any team.</blockquote>

<h2>Core contracts</h2>
<table>
<tr><th>Protocol</th><th>Chain</th><th>Controller</th><th>Changes behind a timelock</th><th>Upgradeable (ERC-1967)</th></tr>
%%CORE%%
</table>
<p class="sub">Core-contract facts read at the chain head on %%ASOF%%. More protocols are added only when the probe resolves their full control path from a curated governance entry point (not a token address), so no row implies an absence the read did not actually establish.</p>

<h2>Governance change delay &amp; last change observed</h2>
<p>A second lens: where a protocol's on-chain governance routes changes through a timelock, the delay read at that timelock, and the last admin change <strong>observed live</strong> on its governance contracts by the <a href="./">admin-feed</a>. Entry points are the documented governance contracts in <a href="https://github.com/imal1ice/admin-feed/blob/main/control/protocols.json">admin-feed's control registry</a> (each with a public source). Listed alphabetically — a reference, not a ranking.</p>
<table>
<tr><th>Protocol</th><th>Governance timelock delay</th><th>Last admin change observed</th></tr>
%%GOV%%
</table>
<p class="sub">The last column updates hourly from the live feed; a dash means no admin event on these contracts since the feed began (30 Jul 2026) — a long quiet period is itself information. Protocols whose changes pass through on-chain voting rather than a single fixed timelock (e.g. Curve, Balancer, Lido's dual governance, Sky) are not one number, so they are omitted here rather than reduced to one.</p>

<h2>Method</h2>
<p>Each core-contract row is <code>ownerwatch probe &lt;governance-entry&gt; --rpc &lt;rpc&gt; --json</code>, walking owners, proxy admins and roles to the controller that can change the contract, and reading any timelock delay on the way. The governance delays are read the same way from the registry's timelock contracts; the last-change column is the latest event on those contracts in the live feed. The generator is <a href="https://github.com/imal1ice/admin-feed/blob/main/transparency_gen.py">transparency_gen.py</a>. Nothing is sent on-chain.</p>

<h2>About</h2>
<p>ownerwatch is free and MIT-licensed; it monitors and audits exactly these control surfaces. If you want your own deployment mapped — every owner, proxy admin, role holder and Safe signer, with a written report and a monitoring config — or a chain-verified <a href="https://github.com/imal1ice/ownerwatch/blob/main/docs/disclosure-quickstart.md">ERC-8241 control disclosure</a> wired into your CI, write to <a href="mailto:imal1ice@proton.me">imal1ice@proton.me</a>. Before anything is paid I share the terms, including where I am based, so you can decide whether you are able to work with me.</p>

<footer><a href="./">← admin-feed</a> · <a href="report.html">Report: who controls 36 DeFi protocols</a> · <a href="https://github.com/imal1ice/admin-feed">source</a> · updated %%GEN%%</footer>
</body></html>"""


def render_transparency(rows: list[dict]) -> str:
    """Neutral control-surface reference: static chain-read facts + a LIVE 'last admin change observed'
    column computed from the feed's alerts (matched by the registry's sourced contract addresses)."""
    sysmap: dict[str, set] = {}
    if CONTROL.exists():
        systems = json.loads(CONTROL.read_text(encoding="utf-8")).get("systems", {})
        for sid, s in systems.items():
            sysmap[sid] = {(c.get("address") or "").lower() for c in s.get("contracts", [])}

    def last_change(sid: str):
        addrs = sysmap.get(sid, set())
        ts = [r.get("ts") for r in rows if (r.get("contract") or "").lower() in addrs and r.get("ts")]
        return max(ts)[:10] if ts else None

    core = "\n".join(
        f"<tr><td>{html.escape(p)}</td><td>{html.escape(ch)}</td><td>{html.escape(ct)}</td><td>{html.escape(tl)}</td><td>{html.escape(up)}</td></tr>"
        for p, ch, ct, tl, up in TRANS_CORE)
    gov = "\n".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(delay)}</td><td>{last_change(sid) or '—'}</td></tr>"
        for name, delay, sid in TRANS_GOV)
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (TRANS_TEMPLATE.replace("%%CORE%%", core).replace("%%GOV%%", gov)
            .replace("%%ASOF%%", TRANS_ASOF).replace("%%GEN%%", gen))


SITEMAP_PAGES = ["", "transparency.html", "disclosures.html", "report.html", "control/", "activity.html", "work.html"]


def render_sitemap() -> str:
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    urls = "".join(f"<url><loc>{SITE}{p}</loc><lastmod>{today}</lastmod></url>" for p in SITEMAP_PAGES)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>\n"


OW_BLOB = "https://github.com/imal1ice/ownerwatch/blob/main/examples/erc-8241/"
DISCLOSURES = [  # (protocol, what it shows, records verified clean, example file)
    ("Aave V3 (Ethereum core)", "Pool, addresses provider and ACLManager — 24 role holders and two timelocks, replayed from the logs.", "89", "aave-v3-drafted.json"),
    ("Compound III (USDC)", "Comet and Configurator, upgradeable only through a proxy admin owned by the 48-hour Compound Timelock.", "12", "compound-iii-usdc.json"),
    ("Uniswap V3 Factory", "a pure ownership chain resolving to the Uniswap Timelock (48h) — no roles, no proxy.", "8", "uniswap-v3.json"),
    ("Morpho Blue", "an immutable singleton owned by a multisig — no upgrade path at all.", "6", "morpho-blue.json"),
]

DISCLOSURES_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chain-verified control disclosures (ERC-8241)</title>
<link rel="icon" type="image/png" href="favicon.png">
<meta name="description" content="Machine-checkable ERC-8241 control disclosures for major DeFi protocols, each verified clean against on-chain state with ownerwatch.">
<meta property="og:type" content="website">
<meta property="og:title" content="Chain-verified control disclosures (ERC-8241)">
<meta property="og:description" content="Machine-checkable ERC-8241 control disclosures for major DeFi protocols, each verified clean against the chain with ownerwatch.">
<meta property="og:url" content="https://imal1ice.github.io/admin-feed/disclosures.html">
<meta property="og:image" content="https://imal1ice.github.io/admin-feed/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e5e5e5}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--muted:#999;--line:#2a2a2a}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px} p.sub{color:var(--muted);margin:0 0 20px}
h2{font-size:14px;color:var(--muted);font-weight:600;letter-spacing:.04em;text-transform:uppercase;margin:28px 0 8px}
a{color:inherit} code{font-size:13px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0} td,th{text-align:left;padding:6px 10px 6px 0;border-bottom:1px solid var(--line);vertical-align:top} th{color:var(--muted);font-weight:600}
footer{color:var(--muted);font-size:13px;margin-top:32px}
</style></head><body>
<h1>Chain-verified control disclosures</h1>
<p class="sub"><a href="./">admin-feed</a> · ERC-8241 control disclosures by <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a></p>

<p>A control disclosure states, in a machine-checkable file, exactly <strong>who can change a protocol's contracts</strong> — every owner, proxy admin, role holder, Safe signer and timelock. <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a> drafts it from the chain and <code>disclosure check</code> verifies every claim against on-chain state, so a reader never has to trust the prose. Here are four, for public protocols, each checking clean at a pinned block.</p>

<table>
<tr><th>Protocol</th><th>What the disclosure shows</th><th>Records verified</th><th>Disclosure</th></tr>
%%ROWS%%
</table>
<p class="sub">“Records verified” is how many claims the checker settled against the chain with zero mismatches and zero undisclosed powers. Each example is pinned to a block; re-draft at the current block to re-verify.</p>

<h2>How it works</h2>
<p>Three commands: <code>disclosure draft</code> writes the file from the chain, <code>disclosure check</code> verifies it (and fails CI on any drift), and the ownerwatch GitHub Action emits a live status badge that goes red the moment on-chain control drifts from the disclosure. The 10-minute walk-through is the <a href="https://github.com/imal1ice/ownerwatch/blob/main/docs/disclosure-quickstart.md">control-disclosure quickstart</a>.</p>

<h2>Want yours?</h2>
<p>If you publish a governance or security page, a machine-checkable disclosure turns “trust our docs” into “check the chain.” I draft it, chain-verify every claim, and wire the CI check and the live badge into your repo. Write to <a href="mailto:imal1ice@proton.me">imal1ice@proton.me</a>. Before anything is paid I share the terms, including where I am based, so you can decide whether you are able to work with me.</p>

<footer><a href="./">← admin-feed</a> · <a href="transparency.html">Control surface at a glance</a> · <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a></footer>
</body></html>"""


def render_disclosures() -> str:
    rows = "\n".join(
        f'<tr><td>{html.escape(name)}</td><td>{html.escape(what)}</td><td>{html.escape(n)} records ok</td>'
        f'<td><a href="{OW_BLOB}{html.escape(f)}">JSON</a></td></tr>'
        for name, what, n, f in DISCLOSURES)
    return DISCLOSURES_TEMPLATE.replace("%%ROWS%%", rows)


def main() -> None:
    rows = load()
    DOCS.mkdir(exist_ok=True)
    for asset in ("favicon.png", "og-image.png"):
        src = ROOT / "assets" / asset
        if src.exists():
            shutil.copyfile(src, DOCS / asset)
    (DOCS / "index.html").write_text(render_html(rows), encoding="utf-8")
    (DOCS / "feed.xml").write_text(render_rss(rows), encoding="utf-8")
    if CONTROL.exists():
        (DOCS / "control").mkdir(exist_ok=True)
        data, page = render_control(rows)
        (DOCS / "control" / "index.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        (DOCS / "control" / "index.html").write_text(page, encoding="utf-8")
    (DOCS / "transparency.html").write_text(render_transparency(rows), encoding="utf-8")
    (DOCS / "disclosures.html").write_text(render_disclosures(), encoding="utf-8")
    (DOCS / "sitemap.xml").write_text(render_sitemap(), encoding="utf-8")
    (DOCS / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}sitemap.xml\n", encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    print(f"rendered {len(rows)} alerts")


if __name__ == "__main__":
    main()
