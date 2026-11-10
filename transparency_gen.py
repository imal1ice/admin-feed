"""Transparency-index generator (idea 38). Probes a CURATED list of public protocols and prints ONLY
neutral on-chain facts (timelock delay, upgradeability, controller kind) for a L2BEAT/DeFiScan-style reference.

FAIRNESS (validated 2026-11-09): probe each protocol at its real GOVERNANCE entry point, not a token address.
Probing a token (e.g. stETH, rETH) reads the token's own admin, not the DAO, so a timelock can read as "none"
when one exists elsewhere — misleading. Only publish rows whose control path the probe resolves cleanly.
"""
import json, subprocess, sys, time
OW="/home/claude/projects/ownerwatch/.venv/bin/ownerwatch"
RPC="https://ethereum-rpc.publicnode.com"

# Blue-chip, public protocols only (no private targets). Neutral reference.
# Curated GOVERNANCE entry points (not token addresses). Each was verified to read a clean control path.
SEED=[
    ("Uniswap V3 Factory", "0x1F98431c8aD98523631AE4a59f267346ea31F984"),
    ("Compound III (USDC Comet)", "0xc3d688B66703497DAA19211EEdff47f25384cdc3"),
    ("Compound V2 Comptroller", "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B"),
    ("Aave V3 Pool", "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"),
    ("Ethena (USDe)", "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3"),
    ("Morpho Blue", "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"),
]
# EXCLUDED for fairness (read did not resolve the real governance delay from this address, so a row would
# falsely imply "no timelock"): Lido stETH, Rocket Pool rETH (token addresses), Spark SparkLend Pool
# (Maker-governed; the Maker pause-proxy delay is not resolved from the pool address). Add these only with
# their correct governance entry point once verified.

def dur(s):
    if s is None: return None
    h=s//3600
    return f"{h}h" if h and s%3600==0 else (f"{s//86400}d" if s%86400==0 else f"{s}s")

def facts(name, addr):
    try:
        out=subprocess.run([OW,"probe",addr,"--label",name,"--rpc",RPC,"--json"],
                           capture_output=True,text=True,timeout=150)
        d=json.loads(out.stdout)
    except Exception as e:
        return {"name":name,"err":str(e)[:60]}
    nodes={n["address"]:n for n in d.get("nodes",[])}
    root=nodes.get(addr) or next(iter(nodes.values()),None)
    # walk controllers
    seen=set(); cur=root; path=[]; timelock=None; terminal=None
    while cur and cur["address"] not in seen:
        seen.add(cur["address"]); path.append(cur)
        if cur.get("kind") in ("timelock","legacy-timelock") and cur.get("delay") is not None:
            timelock=timelock or cur.get("delay")
        nxt=cur.get("proxy_admin") or cur.get("owner") or cur.get("admin") or cur.get("authority")
        if not nxt or nxt==cur["address"] or nxt not in nodes:
            terminal=cur; break
        cur=nodes[nxt]
    terminal=terminal or (path[-1] if path else None)
    # describe terminal controller neutrally
    def describe(n):
        if n is None: return "not read"
        k=n.get("kind")
        if k=="safe" and n.get("safe_threshold") is not None:
            return f"{n['safe_threshold']}-of-{len(n.get('safe_owners') or [])} Safe"
        if k in ("timelock","legacy-timelock"):
            return f"timelock ({dur(n.get('delay'))})"
        if k=="eoa": return "a single externally-owned account"
        return "a contract"
    upgr = any(n.get("implementation") or n.get("beacon") or n.get("proxy_admin") for n in path) or root.get("kind")=="proxy"
    return {"name":name,"controlled_by":describe(terminal),
            "timelock":(dur(timelock) if timelock is not None else "none read"),
            "upgradeable":("yes" if upgr else "not in state read"),
            "incomplete":bool(d.get("incomplete"))}

for name,addr in SEED:
    f=facts(name,addr)
    print(json.dumps(f))
