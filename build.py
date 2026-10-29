"""Render docs/index.html and docs/feed.xml from alerts.jsonl. Standard library only."""
from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).parent
ALERTS = ROOT / "alerts.jsonl"
DOCS = ROOT / "docs"
SITE = "https://imal1ice.github.io/admin-feed/"
EXPLORERS = {"ethereum": "https://etherscan.io", "base": "https://basescan.org",
             "arbitrum": "https://arbiscan.io", "optimism": "https://optimistic.etherscan.io"}
MAX_PAGE = 500
MAX_RSS = 100


def load() -> list[dict]:
    if not ALERTS.exists():
        return []
    rows = [json.loads(l) for l in ALERTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda r: (r.get("ts", ""), r.get("block", 0)), reverse=True)
    return rows


def tx_url(row: dict) -> str:
    """ownerwatch stores a full explorer URL in tx_hash when explorer_url is configured, else a bare hash."""
    tx = row.get("tx_hash") or ""
    if tx.startswith("http"):
        return tx
    base = EXPLORERS.get(row.get("chain", ""), "")
    return f"{base}/tx/{tx}" if base and tx.startswith("0x") else ""


def tx_link(row: dict) -> str:
    url = tx_url(row)
    h = url.rsplit("/", 1)[-1] if url else (row.get("tx_hash") or "-")
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
<p class="sub">Timelock queues, upgrades, role grants, Safe signer changes and queued Safe transactions on major protocols across Ethereum, Arbitrum, Optimism and Base, as they happen. Polled hourly by <a href="https://github.com/imal1ice/ownerwatch">ownerwatch</a> on a free GitHub Actions runner. <a href="report.html">Report: who controls 36 DeFi protocols</a> · <a href="feed.xml">RSS</a> · <a href="https://github.com/imal1ice/admin-feed">source and config</a></p>"""]
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
        guid = f"{r.get('chain')}:{(r.get('tx_hash') or '').rsplit('/', 1)[-1]}:{r.get('contract')}:{r.get('event')}:{r.get('block')}"
        items.append(f"<item><title>{escape(title)}</title><link>{escape(link)}</link><guid isPermaLink=\"false\">{escape(guid)}</guid>"
                     f"<pubDate>{pub}</pubDate><description>{escape(str(r.get('message', '')))} (block {r.get('block')}, {escape(str(r.get('chain')))})</description></item>")
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
}
# A governance decision taking effect. Counted once per transaction: one proposal emits several of these.
EXECUTION_EVENTS = {"CallExecuted", "ExecuteTransaction", "ProposalExecuted", "ExecuteVote", "PayloadExecuted"}


def block_dates(rows: list[dict]) -> dict[int, str]:
    """Block number -> UTC date, read once over JSON-RPC and cached. Alerts carry the time they were seen,
    which can trail the block by up to an hour; dates here are the block's own. A block the RPC will not
    answer this run falls back to the alert's date and is retried on the next build."""
    import time
    import urllib.error
    import urllib.request
    cache = {int(k): v for k, v in json.loads(BLOCKTIMES.read_text()).items()} if BLOCKTIMES.exists() else {}
    missing = sorted({r["block"] for r in rows} - cache.keys())
    fetched = 0
    for i in range(0, len(missing), 10):
        body = [{"jsonrpc": "2.0", "id": b, "method": "eth_getBlockByNumber", "params": [hex(b), False]} for b in missing[i:i + 10]]
        req = urllib.request.Request(ETH_RPC, json.dumps(body).encode(), {"Content-Type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    answers = json.loads(resp.read())
                break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 ** attempt * 2)
        else:
            break
        for ans in answers:
            if ans.get("result"):
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
    mine = [{**r, "date": dates[r["block"]]} for r in rows
            if r.get("chain") == "ethereum" and r.get("contract", "").lower() in watched and r.get("block") in dates
            and dates[r["block"]] >= cutoff and r.get("event") in CONTROL_EVENTS | EXECUTION_EVENTS]
    mine.sort(key=lambda r: r["block"], reverse=True)
    changes = [r for r in mine if r["event"] in CONTROL_EVENTS]
    executions = {r.get("tx_hash") for r in mine if r["event"] in EXECUTION_EVENTS}
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


def main() -> None:
    rows = load()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(render_html(rows), encoding="utf-8")
    (DOCS / "feed.xml").write_text(render_rss(rows), encoding="utf-8")
    if CONTROL.exists():
        (DOCS / "control").mkdir(exist_ok=True)
        data, page = render_control(rows)
        (DOCS / "control" / "index.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        (DOCS / "control" / "index.html").write_text(page, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    print(f"rendered {len(rows)} alerts")


if __name__ == "__main__":
    main()
