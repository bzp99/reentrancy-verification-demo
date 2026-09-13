#!/usr/bin/env python3
"""Assemble out/results.json from out/normalized/*.json.

_Authored by Claude Code_ - 2026-09-12.

This file is the seam. Everything upstream of it is replaceable; everything
downstream is pure. A missing normalized file is not a crash - it becomes an
`error` verdict so the page still renders with that column greyed out.
"""
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NORM = ROOT / "out" / "normalized"
OUT = ROOT / "out" / "results.json"

ORDER = ["slither", "mythril", "smtchecker"]

# Line numbers verified against the files; if you edit the contracts, re-check
# them with: grep -n 'msg.sender.call\|= 0;\|-= amount' contracts/*.sol
CASES = [
    {"id": "vulnerable", "title": "VulnerableVault",
     "subtitle": "Interaction before effects",
     "file": "contracts/VulnerableVault.sol",
     "highlight_lines": [20, 23, 24],
     "property_line": 27,
     # deposit() through withdraw(): the attack is told against this excerpt,
     # and every exploit step below points at lines inside it.
     "excerpt": [9, 27]},
    {"id": "safe", "title": "SafeVault",
     "subtitle": "Checks-effects-interactions",
     "file": "contracts/SafeVault.sol",
     "highlight_lines": [18, 19, 21],
     "property_line": 25,
     "excerpt": [9, 25]},
]

PROPERTY = "assert(totalDeposits <= address(this).balance)"

# The attack, in the fewest steps that still make it land. Content, not
# presentation, so it lives here rather than in the renderer.
#
# The third field is the lines of VulnerableVault.sol that the step is about.
# Selecting a step highlights exactly those, so the attack can be walked
# through against the code instead of described beside it. They must lie
# inside the case's `excerpt` range or the highlight points off-screen.
EXPLOIT = [
    ("Deposit once",
     "A contract deposits 1 ether and the vault records it.",
     [10, 11]),
    ("Call withdraw()",
     "The vault reads that balance, and the check passes.",
     [15, 16]),
    ("Re-enter on receive",
     "Ether is sent <em>before</em> the balance is zeroed. Receiving it runs "
     "the attacker's code, which calls <code>withdraw()</code> again.",
     [20]),
    ("Repeat until drained",
     "The writes that would have stopped this run too late – every pass "
     "pays out again against the same stale balance.",
     [23, 24]),
]

EXPLOIT_NOTE = "June 2016: this pattern drained ~3.6M ETH from The DAO."


def git(*args, default="unknown"):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return default


def placeholder(tool_id):
    return {
        "id": tool_id, "name": tool_id.title(), "technique": "-",
        "version": "-", "can_prove": False,
        "results": {c["id"]: {
            "verdict": "error", "headline": "Tool did not run",
            "detail": "No output produced in this pipeline run.",
            "trace": [], "duration_ms": 0} for c in CASES},
    }


def main():
    tools = []
    for tid in ORDER:
        p = NORM / f"{tid}.json"
        if p.exists():
            try:
                tools.append(json.loads(p.read_text()))
                continue
            except json.JSONDecodeError:
                print(f"!! {p} is not valid JSON, treating as a failed run")
        tools.append(placeholder(tid))

    for c in CASES:
        c["source"] = (ROOT / c["file"]).read_text()

    doc = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                        .isoformat(timespec="seconds"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "commit_full": git("rev-parse", "HEAD"),
        "repo": git("config", "--get", "remote.origin.url", default=""),
        "property": PROPERTY,
        "exploit": [list(s) for s in EXPLOIT],
        "exploit_note": EXPLOIT_NOTE,
        "cases": CASES,
        "tools": tools,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2))

    ok = sum(1 for t in tools
             if t["results"]["vulnerable"]["verdict"] != "error")
    print(f"merged {ok}/{len(tools)} tools -> {OUT}")
    # Nonzero only if nothing at all worked.
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
