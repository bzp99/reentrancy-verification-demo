#!/usr/bin/env python3
"""Mythril runner - bounded symbolic execution over EVM bytecode.

_Authored by Claude Code_ - 2026-09-12.

Mythril explores to a bound. Finding nothing means "nothing within the bound",
which is `no_finding`, not `proved` - that distinction is the whole demo.

Two things had to be settled early, both recorded here because they
are easy to get wrong again:

1. solc is supplied from a local cache via SOLCX_BINARY_PATH. Mythril has no
   --solc-binary flag, only --solv, and --solv downloads from
   solc-bin.ethereum.org, which is not always reachable.

2. The SWC-107 findings are filtered to WRITE-after-call. Mythril's
   exploit-proving detectors (Exceptions, EtherThief) do not fire on Solidity
   0.8.26 within any practical timeout - 0.8's checked arithmetic inflates the
   path space - so this runner uses the default pattern detectors. Those fire
   SWC-107 on BOTH contracts, because SafeVault's `assert` reads state after
   the call. Only the vulnerable contract *writes* state after the call, which
   is the actual stale-state hazard, and which mirrors Slither's own
   reentrancy-eth / reentrancy-benign split.
"""
import json

from schema import CONTRACTS, net_args, run, result, emit
from solc_cache import SOLC_VERSION, ensure_solc

IMAGE = "mythril/myth:0.24.8"
TIMEOUT = 420
EXEC_TIMEOUT = 300
TX_COUNT = "3"
CASES = {"vulnerable": "VulnerableVault.sol", "safe": "SafeVault.sol"}

# The hazard is a state WRITE after an untrusted external call. A read after
# the call is the far weaker pattern, and SafeVault has one by construction.
WRITE_AFTER_CALL = "write to persistent state following external call"


def fmt_trace(tx_seq):
    """Compress Mythril's tx_sequence into a few readable lines.

    The first step is always the deployment, which Mythril labels "unknown".
    It carries no information for a reader and just dilutes the two calls that
    actually matter, so drop it.
    """
    if not tx_seq:
        return []
    steps = tx_seq.get("steps", []) if isinstance(tx_seq, dict) else []
    lines = []
    for s in steps:
        name = s.get("name") or ""
        if not name or name == "unknown":
            continue
        val = s.get("value", "0x0")
        lines.append(f"call {name}  value={val}")
    return lines[:6]


def analyze(filename, solc_dir):
    cmd = ["docker", "run", "--rm", *net_args(),
           "-v", f"{CONTRACTS}:/src:ro",
           "-v", f"{solc_dir}:/opt/solcx",
           "-e", "SOLCX_BINARY_PATH=/opt/solcx",
           "--entrypoint", "myth", IMAGE,
           "analyze", f"/src/{filename}", "-o", "json",
           "--execution-timeout", str(EXEC_TIMEOUT),
           "-t", TX_COUNT, "--solv", SOLC_VERSION]
    rc, out, err, ms = run(cmd, timeout=TIMEOUT)

    try:
        data = json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return result("error", "Mythril produced no parseable output",
                      (err or out)[-600:], duration_ms=ms), out

    if data.get("error"):
        return result("error", "Mythril reported an error",
                      str(data["error"])[:600], duration_ms=ms), out

    issues = data.get("issues", [])
    swc107 = [i for i in issues if str(i.get("swc-id")) == "107"]
    writes = [i for i in swc107
              if WRITE_AFTER_CALL in " ".join(i.get("description", "").split()).lower()]

    if writes:
        i = writes[0]
        lines = sorted({w.get("lineno") for w in writes if w.get("lineno")})
        return result(
            "violated",
            f"SWC-107 {i.get('title', 'Reentrancy')} – "
            f"{i.get('severity', '?')} severity",
            "A state write after the external call, reached on a concrete "
            "transaction sequence.",
            facts=[
                ["detector", f"SWC-107 {i.get('title', '')}"],
                ["severity", str(i.get("severity", "?"))],
                ["written after", ", ".join(f"L{n}" for n in lines)],
                ["bound", f"{TX_COUNT} transactions, {EXEC_TIMEOUT}s"],
            ],
            trace=fmt_trace(i.get("tx_sequence")),
            duration_ms=ms,
        ), out

    return result("no_finding",
                  "No state write after the external call",
                  "Nothing within the bound – an absence of evidence, "
                  "not a proof.",
                  facts=[
                      ["bound", f"{TX_COUNT} transactions, {EXEC_TIMEOUT}s"],
                      ["other findings",
                       f"{len(issues)} total, {len(swc107)} SWC-107 pattern "
                       f"warnings with no write after the call"],
                  ],
                  duration_ms=ms), out


def main():
    solc_dir = ensure_solc()
    _, ver, _, _ = run(["docker", "run", "--rm", "--entrypoint", "myth",
                        IMAGE, "version"], 120)
    raws, results = {}, {}
    for case, fn in CASES.items():
        results[case], raws[case] = analyze(fn, solc_dir)
    emit("mythril", "Mythril",
         "Bounded symbolic execution over EVM bytecode – Z3",
         ver.strip() or IMAGE.split(":")[-1], can_prove=False,
         results=results, raw=json.dumps(raws, indent=2))


if __name__ == "__main__":
    main()
