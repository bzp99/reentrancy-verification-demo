# Reentrancy verification demo — implementation plan

A CI-generated, single-file HTML page that runs three analysis tools against one
pair of contracts and shows that only one of them can *prove* the fixed version safe.

Target: demo-ready in roughly one working day, spread over six phases.

---

## 1. What you're building

```
contracts/            two .sol files differing by two lines
      |
      v
tools/run_*.py        three independent runners, each in a pinned Docker image
      |                     |                     |
   raw/slither.json    raw/mythril.json     raw/smtchecker.json
      |                     |                     |
      +---------------------+---------------------+
                            |
                    tools/merge.py          normalizes to one schema,
                            |               fills gaps for tools that failed
                            v
                    out/results.json        <-- the seam. Everything upstream
                            |                   is replaceable; everything
                            v                   downstream is pure.
                    tools/render.py
                            |
                            v
                    out/index.html          single file, no network deps
```

The one structural rule: **nothing but `render.py` knows what HTML looks like, and
`render.py` knows nothing about Docker, solvers, or Solidity.** It reads
`results.json` and writes a page. That means you can iterate on the page design in
milliseconds without re-running a solver, and you can swap or add tools later
without touching the renderer.

### The verdict vocabulary

This is the most important design decision in the whole project, so fix it before
you write anything else. Five values:

| verdict | meaning | who can emit it |
|---|---|---|
| `violated` | a concrete counterexample exists | all three |
| `no_finding` | the analysis completed and reported nothing | Slither, Mythril |
| `proved` | the property holds for all reachable states | SMTChecker only |
| `unknown` | the analysis ran but could not decide (timeout, incompleteness) | Mythril, SMTChecker |
| `error` | the tool crashed, timed out at the process level, or never ran | all three |

`no_finding` and `proved` must never collapse into one another. The entire
argument of the demo is that they are different claims. Keep them distinct in the
schema, distinct in the CSS, and distinct in how you talk about them on stage.

---

## 2. Phase 0 — the spike (do this first, ~90 minutes)

**Do not build the pipeline until this passes.** All three tools have version
sensitivities and you need to know now, not the night before, which ones behave.

Write the two contracts (Phase 1 below), then run each tool by hand:

```bash
mkdir -p spike && cd spike
# ... put VulnerableVault.sol and SafeVault.sol here ...

# 1. Slither
docker run --rm -v "$PWD":/src trailofbits/eth-security-toolbox:nightly \
  slither /src/VulnerableVault.sol --json - | tee slither-vuln.json

# 2. Mythril
docker run --rm -v "$PWD":/src mythril/myth:0.24.8 \
  analyze /src/VulnerableVault.sol -o json --execution-timeout 120 --solv 0.8.26

# 3. SMTChecker
docker run --rm -v "$PWD":/src ethereum/solc:0.8.26 \
  --model-checker-engine chc --model-checker-targets assert \
  --model-checker-solvers z3 --model-checker-timeout 20000 \
  /src/VulnerableVault.sol
```

Then run all three against `SafeVault.sol`.

### Go/no-go criteria

- [ ] Slither reports `reentrancy-eth` on vulnerable, nothing on safe. *(Expected to
      pass. Slither is the reliable one.)*
- [ ] Mythril reports SWC-107 on vulnerable within the timeout. **This is the one
      most likely to fail.** Solidity 0.8's implicit overflow checks inflate the
      path space and Mythril's 0.8.x handling has been uneven.
- [ ] SMTChecker reports an assertion violation on vulnerable **and** an
      informational "proved safe" message on safe. The second half is the one to
      check — if it returns `unknown` instead, your demo loses its punchline.

### If Mythril fails

Two options, in order of preference:

1. Raise `--execution-timeout` to 300 and check whether it's slow rather than
   broken. If it finds it at 300s, keep it — CI has the time, and you can cache.
2. Drop the pair to `pragma solidity 0.7.6` and remove the reliance on 0.8
   checked arithmetic. Mythril is much better behaved there. Cost: someone may
   ask why you're on old Solidity, and the honest answer ("the symbolic executor
   handles it better") is a fine answer.

If neither works, ship with two tools. The table still tells the story.

### If SMTChecker returns `unknown` on the safe contract

Usually means the property is too weak or the loop/mapping handling is choking.
Try narrowing: add `--model-checker-contracts` to target only `SafeVault`, and
make sure the assert is the only target. If it still won't prove, simplify the
property (e.g. drop `totalDeposits` and assert only `balances[msg.sender] == 0`
after the call). A simpler proved property beats a richer unproved one.

### While you're here

Record the exact versions and the exact `errorCode` values SMTChecker emits.
Dump the raw standard-json output and note what code accompanies the assertion
violation and what code accompanies the proved-safe info line. The parser in
Phase 2 matches on both code and message text so it survives a version bump, but
you want to know the actual values.

---

## 3. Repo layout

```
.
├── contracts/
│   ├── VulnerableVault.sol
│   └── SafeVault.sol
├── tools/
│   ├── schema.py            shared types + normalized-result writer
│   ├── run_slither.py
│   ├── run_mythril.py
│   ├── run_smtchecker.py
│   ├── merge.py
│   └── render.py
├── fixtures/
│   └── results.known-good.json    committed fallback for demo day
├── fonts/                   optional, subset .woff2 files, inlined by renderer
├── .github/workflows/
│   ├── demo.yml             build + deploy
│   └── codeql-sarif.yml     (optional) Slither SARIF → code scanning
├── out/                     gitignored
├── Makefile
└── README.md
```

---

## 4. Phase 1 — the contracts

Two files, differing by the position of two statements. That difference is the
demo, so keep everything else byte-identical.

**`contracts/VulnerableVault.sol`**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @notice Deliberately vulnerable. Mirrors the DAO withdrawal pattern.
contract VulnerableVault {
    mapping(address => uint256) public balances;
    uint256 public totalDeposits;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
        totalDeposits += msg.value;
    }

    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "nothing to withdraw");

        // Interaction before effects: control transfers to an unknown callee
        // which may re-enter withdraw() while balances[msg.sender] is stale.
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");

        balances[msg.sender] = 0;
        totalDeposits -= amount;

        /// @dev Solvency invariant: the vault never owes more than it holds.
        assert(totalDeposits <= address(this).balance);
    }
}
```

**`contracts/SafeVault.sol`** — identical, with the two state writes hoisted
above the call:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @notice Checks-effects-interactions. Same invariant, same assertion.
contract SafeVault {
    mapping(address => uint256) public balances;
    uint256 public totalDeposits;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
        totalDeposits += msg.value;
    }

    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "nothing to withdraw");

        balances[msg.sender] = 0;
        totalDeposits -= amount;

        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");

        /// @dev Solvency invariant: the vault never owes more than it holds.
        assert(totalDeposits <= address(this).balance);
    }
}
```

Note the line numbers of the `call` and the two state writes in each file — the
renderer highlights them, and you'll hardcode them in `merge.py`. If you edit the
contracts, update the highlights.

---

## 5. Phase 2 — the runners

### `tools/schema.py`

```python
"""Shared schema helpers. Every runner writes the same shape."""
import json, pathlib, subprocess, time

VERDICTS = {"violated", "no_finding", "proved", "unknown", "error"}
RAW = pathlib.Path("out/raw")
NORM = pathlib.Path("out/normalized")


def run(cmd, timeout):
    """Run a command, return (returncode, stdout, stderr, elapsed_ms)."""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = -1, "", f"process timeout after {timeout}s"
    return rc, out, err, int((time.time() - t0) * 1000)


def result(verdict, headline, detail="", trace=None, duration_ms=0):
    assert verdict in VERDICTS, verdict
    return {
        "verdict": verdict,
        "headline": headline,
        "detail": detail,
        "trace": trace or [],
        "duration_ms": duration_ms,
    }


def emit(tool_id, name, technique, version, can_prove, results, raw=None):
    NORM.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (RAW / f"{tool_id}.json").write_text(
            raw if isinstance(raw, str) else json.dumps(raw, indent=2)
        )
    (NORM / f"{tool_id}.json").write_text(json.dumps({
        "id": tool_id, "name": name, "technique": technique,
        "version": version, "can_prove": can_prove, "results": results,
    }, indent=2))
    print(f"[{tool_id}] " + "  ".join(
        f"{k}={v['verdict']}({v['duration_ms']}ms)" for k, v in results.items()))
```

### `tools/run_slither.py`

```python
#!/usr/bin/env python3
import json, sys
from schema import run, result, emit

IMAGE = "trailofbits/eth-security-toolbox:nightly"
CASES = {"vulnerable": "VulnerableVault.sol", "safe": "SafeVault.sol"}


def analyze(filename):
    cmd = ["docker", "run", "--rm", "-v", f"{sys.path[0]}/../contracts:/src:ro",
           IMAGE, "slither", f"/src/{filename}", "--json", "-"]
    rc, out, err, ms = run(cmd, timeout=180)

    # Slither exits nonzero when it finds something. That is not an error.
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return result("error", "Slither produced no parseable output",
                      err[-600:], duration_ms=ms), out

    dets = data.get("results", {}).get("detectors", [])
    reent = [d for d in dets if d.get("check", "").startswith("reentrancy")]
    if reent:
        d = reent[0]
        return result(
            "violated",
            f"{d['check']} — {d.get('impact', '?')} impact",
            d.get("description", "").strip()[:900],
            duration_ms=ms,
        ), out
    return result("no_finding",
                  "No reentrancy detector fired",
                  f"{len(dets)} finding(s) of other kinds.",
                  duration_ms=ms), out


def main():
    rc, ver, _, _ = run(["docker", "run", "--rm", IMAGE, "slither", "--version"], 60)
    raws, results = {}, {}
    for case, fn in CASES.items():
        results[case], raws[case] = analyze(fn)
    emit("slither", "Slither",
         "Static analysis — dataflow over SlithIR",
         ver.strip() or "unknown", can_prove=False,
         results=results, raw=json.dumps(raws, indent=2))


if __name__ == "__main__":
    main()
```

### `tools/run_mythril.py`

```python
#!/usr/bin/env python3
import json, sys
from schema import run, result, emit

IMAGE = "mythril/myth:0.24.8"
SOLV = "0.8.26"
TIMEOUT = 300
CASES = {"vulnerable": "VulnerableVault.sol", "safe": "SafeVault.sol"}


def fmt_trace(tx_seq):
    """Compress Mythril's tx_sequence into a few readable lines."""
    if not tx_seq:
        return []
    steps = tx_seq.get("steps", []) if isinstance(tx_seq, dict) else []
    lines = []
    for s in steps[:6]:
        name = s.get("name") or s.get("input", "")[:10] or "(fallback)"
        val = s.get("value", "0x0")
        lines.append(f"call {name}  value={val}")
    return lines


def analyze(filename):
    cmd = ["docker", "run", "--rm", "-v", f"{sys.path[0]}/../contracts:/src:ro",
           IMAGE, "analyze", f"/src/{filename}", "-o", "json",
           "--execution-timeout", str(TIMEOUT - 60), "--solv", SOLV]
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
    reent = [i for i in issues if i.get("swc-id") == "107"]
    if reent:
        i = reent[0]
        return result(
            "violated",
            f"SWC-107 {i.get('title', 'Reentrancy')} — {i.get('severity', '?')}",
            i.get("description", "").strip()[:900],
            trace=fmt_trace(i.get("tx_sequence")),
            duration_ms=ms,
        ), out
    return result("no_finding",
                  "No SWC-107 within the explored bound",
                  f"Explored to the configured depth and timeout; "
                  f"{len(issues)} issue(s) of other kinds.",
                  duration_ms=ms), out


def main():
    _, ver, _, _ = run(["docker", "run", "--rm", IMAGE, "version"], 60)
    raws, results = {}, {}
    for case, fn in CASES.items():
        results[case], raws[case] = analyze(fn)
    emit("mythril", "Mythril",
         "Symbolic execution over EVM bytecode — Z3",
         ver.strip() or IMAGE.split(":")[-1], can_prove=False,
         results=results, raw=json.dumps(raws, indent=2))


if __name__ == "__main__":
    main()
```

> **Mythril + network:** `--solv` makes the container fetch a solc build on first
> run. Bake it in or pre-pull the image and warm the cache, or it will fail on a
> conference wifi. See Phase 6.

### `tools/run_smtchecker.py`

```python
#!/usr/bin/env python3
import json, pathlib, sys
from schema import run, result, emit

IMAGE = "ethereum/solc:0.8.26"
CONTRACTS = pathlib.Path(__file__).parent.parent / "contracts"
CASES = {"vulnerable": ("VulnerableVault.sol", "VulnerableVault"),
         "safe":       ("SafeVault.sol", "SafeVault")}

# Verify these in Phase 0 — the parser also matches on message text so a
# version bump that renumbers them will not silently break the demo.
CODE_VIOLATION = 6328   # CHC: assertion violation happens here
CODE_PROVED    = 1391   # CHC: N verification condition(s) proved safe


def standard_json(filename, contract):
    src = (CONTRACTS / filename).read_text()
    return json.dumps({
        "language": "Solidity",
        "sources": {filename: {"content": src}},
        "settings": {
            "modelChecker": {
                "engine": "chc",
                "targets": ["assert"],
                "solvers": ["z3"],
                "timeout": 20000,
                "contracts": {filename: [contract]},
                "showProvedSafe": True,
            },
            "outputSelection": {"*": {"*": []}},
        },
    })


def classify(errors, ms):
    violations = [e for e in errors
                  if e.get("errorCode") == CODE_VIOLATION
                  or "assertion violation" in e.get("message", "").lower()]
    if violations:
        e = violations[0]
        msg = e.get("formattedMessage") or e.get("message", "")
        trace = [ln.strip() for ln in msg.splitlines()
                 if "=" in ln and ("Counterexample" in msg)][:8]
        return result("violated",
                      "CHC: assertion violation — counterexample found",
                      msg.strip()[:1200], trace=trace, duration_ms=ms)

    proved = [e for e in errors
              if e.get("errorCode") == CODE_PROVED
              or "proved safe" in e.get("message", "").lower()]
    if proved:
        return result("proved",
                      "CHC: verification condition proved safe",
                      "The solvency assertion holds in every reachable state, "
                      "for unbounded transaction sequences, including "
                      "re-entrant callbacks from unknown external code.",
                      duration_ms=ms)

    fatal = [e for e in errors if e.get("severity") == "error"]
    if fatal:
        return result("error", "Compilation failed",
                      fatal[0].get("message", "")[:600], duration_ms=ms)

    return result("unknown",
                  "CHC could not decide within the timeout",
                  "No counterexample and no proof. Raise the model-checker "
                  "timeout or simplify the property.", duration_ms=ms)


def analyze(filename, contract):
    cmd = ["docker", "run", "--rm", "-i", IMAGE, "--standard-json"]
    inp = standard_json(filename, contract)
    import subprocess, time
    t0 = time.time()
    p = subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=180)
    ms = int((time.time() - t0) * 1000)
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return result("error", "solc produced no parseable output",
                      p.stderr[-600:], duration_ms=ms), p.stdout
    return classify(data.get("errors", []), ms), p.stdout


def main():
    _, ver, _, _ = run(["docker", "run", "--rm", IMAGE, "--version"], 60)
    version = next((l.split()[-1] for l in ver.splitlines() if "Version" in l),
                   "0.8.26")
    raws, results = {}, {}
    for case, (fn, contract) in CASES.items():
        results[case], raws[case] = analyze(fn, contract)
    emit("smtchecker", "SMTChecker",
         "Constrained Horn Clause model checking — Z3",
         version, can_prove=True,
         results=results, raw=json.dumps(raws, indent=2))


if __name__ == "__main__":
    main()
```

---

## 6. Phase 3 — merge and fallback

`merge.py` assembles `out/results.json` from whatever normalized files exist.
A missing file is not a crash — it becomes an `error` verdict, and the page still
renders with that column greyed out.

```python
#!/usr/bin/env python3
"""Assemble out/results.json from tools/normalized/*.json."""
import json, pathlib, subprocess, datetime, sys

ROOT = pathlib.Path(__file__).parent.parent
NORM = ROOT / "out/normalized"
OUT = ROOT / "out/results.json"

ORDER = ["slither", "mythril", "smtchecker"]

CASES = [
    {"id": "vulnerable", "title": "VulnerableVault",
     "subtitle": "Interaction before effects",
     "file": "contracts/VulnerableVault.sol",
     "highlight_lines": [19, 22, 23]},
    {"id": "safe", "title": "SafeVault",
     "subtitle": "Checks-effects-interactions",
     "file": "contracts/SafeVault.sol",
     "highlight_lines": [17, 18, 20]},
]

PROPERTY = "assert(totalDeposits <= address(this).balance)"


def git(*args, default="unknown"):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT,
                                       text=True).strip()
    except Exception:
        return default


def main():
    tools = []
    for tid in ORDER:
        p = NORM / f"{tid}.json"
        if p.exists():
            tools.append(json.loads(p.read_text()))
        else:
            tools.append({
                "id": tid, "name": tid.title(), "technique": "—",
                "version": "—", "can_prove": False,
                "results": {c["id"]: {
                    "verdict": "error", "headline": "Tool did not run",
                    "detail": "No output produced in this pipeline run.",
                    "trace": [], "duration_ms": 0} for c in CASES},
            })

    for c in CASES:
        c["source"] = (ROOT / c["file"]).read_text()

    doc = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                        .isoformat(timespec="seconds"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "commit_full": git("rev-parse", "HEAD"),
        "repo": git("config", "--get", "remote.origin.url", default=""),
        "property": PROPERTY,
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
```

**Promote a known-good fixture once the pipeline is green:**

```bash
make verify && cp out/results.json fixtures/results.known-good.json && git add -f fixtures/
```

`render.py` takes `--fallback` so that a catastrophic pipeline failure still
produces a page.

---

## 7. Phase 4 — the renderer

### Design direction

Before writing CSS, fix the direction, because the default for a security tool
demo is a near-black terminal with an acid-green accent, and that reads as
generic from the back of a room.

The subject here is *proof*: SAT/UNSAT, counterexamples, verification
certificates. The reference object is a lab report or a proof transcript, not a
hacker console. So: a cool paper ground, ink-dark text, and hairline rules.

**The structural idea, and the whole reason the page works:** don't encode the
three verdicts as three coloured badges. Encode them as three different *kinds of
cell*.

- `violated` — a filled cell, dense with the counterexample trace. Visually heavy.
- `no_finding` — a hollow cell. Hairline outline, a single rule through it, no
  content. It should look like an *absence*, because that's exactly what it is.
- `proved` — a filled cell with a solid proof mark (∎) and the property restated.

The result is that in the "safe" column, Slither and Mythril are visibly *empty*
and SMTChecker is visibly *full*. Someone across the room gets the argument before
reading a single word. That is the demo.

**Tokens:**

```
ground    #E9EDF0   cool paper
ink       #14181B   body text
rule      #C3CBD2   hairlines
muted     #8A96A1   absence, secondary text
violated  #8C2F1E   oxblood
proved    #1B4D5C   deep teal-ink
```

**Type:** IBM Plex Sans for prose, IBM Plex Mono for code, traces, and verdict
lines. One superfamily, two clearly distinct voices, both OFL so you can subset
and inline them. Mono here is carrying actual code, not decorating labels.

Subset and inline (no CDN — event wifi is not a dependency you want):

```bash
pip install fonttools brotli
pyftsubset IBMPlexSans-Regular.ttf --output-file=fonts/sans.woff2 \
  --flavor=woff2 --layout-features='' \
  --unicodes=U+0020-007E,U+2014,U+2192,U+220E
# repeat for IBMPlexSans-SemiBold, IBMPlexMono-Regular, IBMPlexMono-SemiBold
```

If `fonts/` is empty the renderer falls back to system stacks, so this step is
optional and can be done last.

### `tools/render.py`

```python
#!/usr/bin/env python3
import argparse, base64, html, json, pathlib

ROOT = pathlib.Path(__file__).parent.parent
FONTS = ROOT / "fonts"

CSS = """
:root{--ground:#E9EDF0;--ink:#14181B;--rule:#C3CBD2;--muted:#8A96A1;
--violated:#8C2F1E;--proved:#1B4D5C;--paper:#F5F7F9}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font-family:var(--sans);font-size:17px;line-height:1.55;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:56px 32px 96px}
h1{font-size:38px;line-height:1.15;font-weight:600;margin:0 0 12px;
max-width:22ch;letter-spacing:-0.015em}
.lede{max-width:62ch;color:#3A444C;margin:0 0 8px}
.prop{font-family:var(--mono);font-size:15px;background:var(--paper);
border:1px solid var(--rule);padding:10px 14px;display:inline-block;
margin:20px 0 40px}
.grid{display:grid;grid-template-columns:200px 1fr 1fr;gap:1px;
background:var(--rule);border:1px solid var(--rule);margin-bottom:48px}
.grid>*{background:var(--paper);padding:18px 20px}
.hd{background:var(--ground);font-weight:600}
.hd small{display:block;font-weight:400;color:var(--muted);
font-family:var(--mono);font-size:12.5px;margin-top:4px}
.toolcell{display:flex;flex-direction:column;justify-content:center}
.toolcell .tech{font-size:13.5px;color:var(--muted);margin-top:2px}
.toolcell .ver{font-family:var(--mono);font-size:12px;color:var(--muted);
margin-top:6px}
.v-head{font-family:var(--mono);font-size:14px;font-weight:600;
display:flex;gap:9px;align-items:baseline}
.v-violated{color:var(--violated)}
.v-proved{color:var(--proved)}
.v-no_finding,.v-unknown,.v-error{color:var(--muted)}
.cell-no_finding,.cell-unknown,.cell-error{
background:repeating-linear-gradient(135deg,transparent,transparent 7px,
rgba(138,150,161,.09) 7px,rgba(138,150,161,.09) 8px)}
.detail{font-size:14px;margin-top:9px;color:#3A444C;max-width:56ch}
.trace{font-family:var(--mono);font-size:12.5px;margin-top:12px;
border-left:2px solid var(--violated);padding-left:12px;color:#3A444C;
white-space:pre-wrap}
.qed{font-family:var(--mono);font-size:13px;margin-top:12px;
color:var(--proved);border-top:1px solid var(--rule);padding-top:10px}
.ms{font-family:var(--mono);font-size:11.5px;color:var(--muted);
margin-left:auto;font-weight:400}
h2{font-size:22px;font-weight:600;margin:0 0 6px}
.srcs{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:14px}
pre{font-family:var(--mono);font-size:12.5px;line-height:1.6;
background:var(--paper);border:1px solid var(--rule);padding:16px;
overflow-x:auto;margin:10px 0 0}
pre .hl{background:rgba(140,47,30,.13);display:block;
margin:0 -16px;padding:0 16px}
pre.safe .hl{background:rgba(27,77,92,.12)}
footer{margin-top:64px;border-top:1px solid var(--rule);padding-top:18px;
font-family:var(--mono);font-size:12.5px;color:var(--muted);
display:flex;flex-wrap:wrap;gap:22px}
a{color:inherit}
@media (max-width:900px){.grid,.srcs{grid-template-columns:1fr}
.hd{border-top:1px solid var(--rule)}}
@media (prefers-reduced-motion:no-preference){}
"""

GLYPH = {"violated": "✕", "proved": "∎", "no_finding": "○",
         "unknown": "?", "error": "!"}
LABEL = {"violated": "COUNTEREXAMPLE FOUND", "proved": "PROVED SAFE",
         "no_finding": "NO FINDING", "unknown": "UNDECIDED",
         "error": "DID NOT RUN"}


def fonts_css():
    faces, names = [], {"sans": "PlexSans", "mono": "PlexMono"}
    for key, fam in names.items():
        f = FONTS / f"{key}.woff2"
        if f.exists():
            b64 = base64.b64encode(f.read_bytes()).decode()
            faces.append(f"@font-face{{font-family:'{fam}';font-display:swap;"
                         f"src:url(data:font/woff2;base64,{b64})format('woff2')}}")
    sans = "'PlexSans'," if (FONTS / "sans.woff2").exists() else ""
    mono = "'PlexMono'," if (FONTS / "mono.woff2").exists() else ""
    faces.append(f":root{{--sans:{sans}ui-sans-serif,system-ui,sans-serif;"
                 f"--mono:{mono}ui-monospace,'SF Mono',Menlo,monospace}}")
    return "\n".join(faces)


def source_block(case):
    hl = set(case.get("highlight_lines", []))
    cls = "safe" if case["id"] == "safe" else ""
    lines = []
    for n, ln in enumerate(case["source"].splitlines(), 1):
        esc = html.escape(ln) or "&nbsp;"
        lines.append(f'<span class="hl">{esc}</span>' if n in hl else esc)
    return f'<pre class="{cls}">' + "\n".join(lines) + "</pre>"


def cell(res):
    v = res["verdict"]
    parts = [f'<div class="v-head v-{v}"><span>{GLYPH[v]}</span>'
             f'<span>{LABEL[v]}</span>'
             f'<span class="ms">{res["duration_ms"]} ms</span></div>']
    if v != "no_finding":
        if res.get("headline"):
            parts.append(f'<div class="detail"><strong>'
                         f'{html.escape(res["headline"])}</strong></div>')
        if res.get("detail"):
            parts.append(f'<div class="detail">'
                         f'{html.escape(res["detail"])}</div>')
    if res.get("trace"):
        parts.append('<div class="trace">'
                     + html.escape("\n".join(res["trace"])) + "</div>")
    if v == "proved":
        parts.append('<div class="qed">Holds for all reachable states, '
                     'unbounded transaction depth. ∎</div>')
    return f'<div class="cell-{v}">' + "".join(parts) + "</div>"


def render(d):
    cases = d["cases"]
    g = [f'<div class="hd">Tool</div>']
    for c in cases:
        g.append(f'<div class="hd">{html.escape(c["title"])}'
                 f'<small>{html.escape(c["subtitle"])}</small></div>')
    for t in d["tools"]:
        g.append(f'<div class="toolcell"><div><strong>'
                 f'{html.escape(t["name"])}</strong></div>'
                 f'<div class="tech">{html.escape(t["technique"])}</div>'
                 f'<div class="ver">{html.escape(str(t["version"]))}</div></div>')
        for c in cases:
            g.append(cell(t["results"][c["id"]]))

    srcs = "".join(f"<div><h2>{html.escape(c['title'])}</h2>"
                   f"{source_block(c)}</div>" for c in cases)

    repo = d.get("repo", "").replace("git@github.com:", "https://github.com/") \
                            .replace(".git", "")
    commit = (f'<a href="{repo}/commit/{d["commit_full"]}">{d["commit"]}</a>'
              if repo.startswith("http") else d["commit"])

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reentrancy — three analyses, one contract pair</title>
<style>{fonts_css()}{CSS}</style></head><body><div class="wrap">
<h1>Two lines apart. Only one tool can prove it.</h1>
<p class="lede">The same withdrawal pattern that drained the DAO, and its
checks-effects-interactions fix. Three analyses run on every commit. All three
find the bug; one of them can certify the fix.</p>
<div class="prop">{html.escape(d["property"])}</div>
<div class="grid">{"".join(g)}</div>
<h2>The difference</h2>
<div class="srcs">{srcs}</div>
<footer><span>generated {html.escape(d["generated_at"])}</span>
<span>commit {commit}</span>
<span>{" · ".join(html.escape(f"{t['name']} {t['version']}") for t in d["tools"])}</span>
</footer></div></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="out/results.json")
    ap.add_argument("--fallback", default="fixtures/results.known-good.json")
    ap.add_argument("--output", default="out/index.html")
    a = ap.parse_args()

    src = pathlib.Path(a.input)
    if not src.exists() or src.stat().st_size < 100:
        src = pathlib.Path(a.fallback)
        print(f"!! falling back to {src}")
    doc = json.loads(src.read_text())
    out = pathlib.Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(doc))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
```

### `Makefile`

```make
.PHONY: spike verify render demo serve clean pull

pull:
	docker pull trailofbits/eth-security-toolbox:nightly
	docker pull mythril/myth:0.24.8
	docker pull ethereum/solc:0.8.26

verify:
	@mkdir -p out/raw out/normalized
	-python3 tools/run_slither.py
	-python3 tools/run_smtchecker.py
	-python3 tools/run_mythril.py
	python3 tools/merge.py

render:
	python3 tools/render.py

demo: verify render
	@echo "open out/index.html"

serve: render
	python3 -m http.server 8000 --directory out

clean:
	rm -rf out
```

The leading `-` on the runner lines is deliberate: one tool failing must not stop
the others.

---

## 8. Phase 5 — GitHub setup

### Create the repo

Public, so Pages is free and the URL is shareable. Name it something that reads
well on a slide.

```bash
gh repo create <org>/reentrancy-verification-demo --public --source=. --push
```

### Enable Pages

`Settings → Pages → Build and deployment → Source: GitHub Actions`.
Not "Deploy from a branch" — the workflow below publishes an artifact directly.

### `.github/workflows/demo.yml`

```yaml
name: verify and publish

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "17 5 * * *"     # nightly, so the page timestamp stays fresh
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write
  security-events: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  slither:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: mkdir -p out/raw out/normalized
      - run: python3 tools/run_slither.py
        continue-on-error: true
      - uses: actions/upload-artifact@v4
        with: { name: n-slither, path: out/normalized/, if-no-files-found: ignore }

  smtchecker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: mkdir -p out/raw out/normalized
      - run: python3 tools/run_smtchecker.py
        continue-on-error: true
      - uses: actions/upload-artifact@v4
        with: { name: n-smtchecker, path: out/normalized/, if-no-files-found: ignore }

  mythril:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - run: mkdir -p out/raw out/normalized
      - run: python3 tools/run_mythril.py
        continue-on-error: true
      - uses: actions/upload-artifact@v4
        with: { name: n-mythril, path: out/normalized/, if-no-files-found: ignore }

  build:
    needs: [slither, smtchecker, mythril]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/download-artifact@v4
        with: { path: dl, pattern: n-*, merge-multiple: true }
      - run: |
          mkdir -p out/normalized
          cp -v dl/*.json out/normalized/ || true
      - run: python3 tools/merge.py || true
      - run: python3 tools/render.py
      - run: cp out/results.json out/index.html /tmp/ && ls -la out
      - uses: actions/upload-artifact@v4
        with: { name: demo-page, path: out/ }
      - uses: actions/upload-pages-artifact@v3
        if: github.ref == 'refs/heads/main'
        with: { path: out }

  deploy:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - id: deploy
        uses: actions/deploy-pages@v4
```

### Slither → code scanning (the PR annotation)

This is the piece that makes "runs in CI/CD" concrete. Add to the `slither` job:

```yaml
      - run: |
          docker run --rm -v "$PWD/contracts":/src:ro \
            trailofbits/eth-security-toolbox:nightly \
            slither /src/VulnerableVault.sol --sarif - > slither.sarif || true
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with: { sarif_file: slither.sarif }
```

Needs `Settings → Code security → Code scanning` enabled on the repo.

### The demo PR

Open a pull request that *introduces* the vulnerability — branch from a state
where `VulnerableVault.sol` is safe, move the two state writes below the call,
push. Leave it open. You now have a permanent URL showing the reentrancy flagged
inline on the exact line of the diff, with a red check on the PR.

Keep that tab open next to the Pages tab. Page proves the analysis; PR proves the
workflow.

---

## 9. Phase 6 — demo-day hardening

- [ ] **Local copy.** `git clone` + `make demo` on the presenting laptop, and
      `out/index.html` saved somewhere you can find it in five seconds. Do not
      rely on Pages resolving over event wifi.
- [ ] **Pre-pull every image** on that laptop, and run the pipeline once offline
      with wifi disabled to confirm nothing reaches for the network. Mythril's
      `--solv` is the usual offender.
- [ ] **Fixture committed.** `fixtures/results.known-good.json` in the repo, and
      confirm `python3 tools/render.py --input /nonexistent` still produces a page.
- [ ] **Nightly run green** for at least two consecutive nights before the event.
      A footer timestamp from twelve hours ago reads as live infrastructure; one
      from three weeks ago reads as a screenshot.
- [ ] **Page under 500 KB** and opens from `file://` with no console errors.
- [ ] **Zoom test.** Open at 150% and look at it from three metres. If you can't
      tell the empty cells from the full ones, increase the contrast on the hatch
      fill before anything else.
- [ ] **Know your numbers.** Rough wall-clock for each tool, and one sentence on
      what CHC actually does. Someone will ask.

### The 90-second script

1. Two contracts, two lines apart. Here's the property. *(point at the `assert`)*
2. Three tools, every commit. Slither finds it in two seconds, Mythril finds it
   with a concrete transaction sequence.
3. Now the fixed version. *(point at the empty cells)* Slither: nothing. Mythril:
   nothing. But "nothing" is not "safe" — it means the analysis finished without
   a finding.
4. *(point at the full cell)* This one says the assertion holds in every reachable
   state, for unbounded transaction depth, including re-entrant callbacks from
   code that doesn't exist yet. That's a proof, not an absence of evidence.
5. Regenerated on every push and nightly. *(footer timestamp, then the PR tab)*

---

## 10. Time budget

| phase | what | est. |
|---|---|---|
| 0 | spike — confirm all three behave | 1.5 h |
| 1 | contracts | 20 min |
| 2 | three runners + schema | 2 h |
| 3 | merge + fixture | 40 min |
| 4 | renderer + fonts | 2 h |
| 5 | repo, Pages, workflow, demo PR | 1.5 h |
| 6 | hardening + rehearsal | 1 h |

Roughly nine hours. The two that reliably overrun are Phase 0 (if Mythril
misbehaves) and Phase 4 (design iteration). Phase 4 is the safe one to cut — a
plain page with correct verdicts beats a beautiful page with a broken pipeline.

---

## 11. Known risks

| risk | likelihood | mitigation |
|---|---|---|
| Mythril doesn't fire on 0.8.26 | medium | raise timeout, else drop to 0.7.6, else ship two tools |
| SMTChecker returns `unknown` on safe | low–medium | narrow to one contract, simplify the property |
| solc `errorCode` values differ | low | parser matches message text as well as code |
| Event wifi dead | high | local `index.html`, pre-pulled images, offline dry run |
| Slither nightly image changes under you | medium | pin to a dated tag once the spike passes |
| Someone calls Slither "not formal methods" | medium | agree — that's the point of the third column |

The last row is worth rehearsing. If someone raises it, the correct response is
enthusiastic agreement: Slither is a static analyzer, Mythril is a bounded
symbolic executor, and neither can prove anything. That's the argument the table
is making.
