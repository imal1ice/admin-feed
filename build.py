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


def main() -> None:
    rows = load()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(render_html(rows), encoding="utf-8")
    (DOCS / "feed.xml").write_text(render_rss(rows), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    print(f"rendered {len(rows)} alerts")


if __name__ == "__main__":
    main()
