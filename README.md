# Reentrancy: three analyses, one contract pair

Two Solidity contracts that differ by the position of two statements, analysed
on every commit by a static analyser, a symbolic executor, and a model checker.
All three find the bug. Only one can certify the fix.

The output is a single self-contained HTML page: [`out/index.html`](out/index.html).

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
                    out/results.json        <-- the seam
                            |
                            v
                    tools/render.py
                            |
                            v
                    out/index.html          single file, no network deps
```

The one structural rule: **nothing but `render.py` knows what HTML looks like,
and `render.py` knows nothing about Docker, solvers, or Solidity.**

## The verdict vocabulary

| verdict | meaning | who can emit it |
|---|---|---|
| `violated` | a concrete counterexample exists | all three |
| `no_finding` | the analysis completed and reported nothing | Slither, Mythril |
| `proved` | the property holds for all reachable states | SMTChecker only |
| `unknown` | the analysis ran but could not decide | Mythril, SMTChecker |
| `error` | the tool crashed, timed out, or never ran | all three |

`no_finding` and `proved` never collapse into one another. The entire argument
is that they are different claims.

## Current result

The property is `assert(totalDeposits <= address(this).balance)` in both files.

| tool | VulnerableVault | SafeVault | wall clock |
|---|---|---|---|
| Slither | `violated` – `reentrancy-eth`, High | `no_finding` | ~0.6 s |
| Mythril | `violated` – SWC-107 write-after-call | `no_finding` | ~5 min per contract |
| SMTChecker | `violated` – assertion reachable | **`proved`** | ~3 s |

## Running it

```bash
make pull      # the three upstream images
make image     # build the solc + Eldarica image (see below)
make demo      # verify + render, then open out/index.html
make serve     # same, on http://localhost:8000
```

`make verify` runs each tool with a leading `-`, so one failure does not stop
the others. Mythril dominates the wall clock at roughly ten minutes.

## How the page is laid out

Reading order is deliberate: **the attack first, then the verdicts, then the
contracts.** Someone who reads only the first screen should still get the
argument.

- **Above the fold:** the claim, the `withdraw()` body being attacked, the
  four-step exploit, the property, and the full verdict table.
- **Below the fold:** both contracts in full, as reference.

Two details that took some care:

- **Emphasis carries meaning.** In every listing, everything except the point
  is dimmed. Red bands mark the statements whose *order* is the bug; teal bands
  mark the assertion being checked. The same two colours band the table cells,
  so a cell and the line it is talking about are marked alike. Hovering a
  listing restores the dimmed lines for anyone who wants to read it all.
  Caller-controlled builtins (`msg`, `tx`, `this`) are set in the violation
  colour, because the attacker's reach is the subject.
- **The table stays above the fold on screens it was not designed for.** CSS
  height breakpoints tighten the vertical rhythm, and a small script measures
  what is left and scales the block to close the gap exactly. Without
  JavaScript the breakpoints still apply.

Syntax highlighting is a ~40-line tokenizer in `render.py` rather than a
library, because the page must stay self-contained with no network dependency.
Ligatures are explicitly disabled: a coding font renders `=>` as one glyph and
`<=` as an inequality sign, which would mean the page shows something that is
not Solidity.

## Three things that are not in the textbook

These cost most of the setup time and each will produce a confusing failure if
reintroduced, so they are documented rather than buried in the commit log.

### 1. No official solc binary contains a Horn solver

SMTChecker's CHC engine needs z3 or Eldarica. Every published solc binary that
was checked – 0.7.6, 0.8.26 and 0.8.36 – answers:

```
Warning: Solver z3 was selected for SMTChecker but it is not available.
Warning: CHC analysis was not possible since no Horn solver was found and enabled.
```

The WASM build *does* bundle z3, which is why CHC works in Remix, but under
Node it dies with `thread constructor failed: Resource temporarily unavailable`
because emscripten cannot spawn z3's threads.

So [`docker/smtchecker/Dockerfile`](docker/smtchecker/Dockerfile) pairs the
stock `ethereum/solc:0.8.26` binary with Eldarica 2.3, which ships a statically
linked native binary. solc finds it by looking for `eld` on `PATH`.

**The solver is Eldarica, not z3.** The technique – Constrained Horn
Clause model checking – is unchanged, and the footer names the solver.

### 2. solc is supplied from a local cache, not downloaded

Slither (via solc-select) and Mythril (via solcx) both try to fetch a compiler
at run time from `solc-bin.ethereum.org`. Where that host is unreachable the
tools hang and then fail – Slither silently, with exit 1 and *no stdout and no
stderr at all*, which is a genuinely confusing thing to debug.

[`tools/solc_cache.py`](tools/solc_cache.py) extracts the binary once from the
official image into `.cache/solc/` and hands it to both tools:

- `slither --solc /opt/solc`
- Mythril via `SOLCX_BINARY_PATH`, since it has no `--solc-binary` flag

This also means the pipeline runs with no network access once the images are
pulled, which is the point of the offline check.

### 3. Mythril's verdict rests on a filtered pattern detector

Mythril's exploit-proving detectors (`Exceptions`, `EtherThief`) do **not** fire
on either contract on Solidity 0.8.26 within 300 s and three transactions.
0.8's checked arithmetic inflates the path space; this is a known weakness.

Its default pattern detectors do fire – but on *both* contracts, because
`SafeVault`'s `assert` reads state after the external call. Raw, that is a
false positive on the safe contract.

The runner therefore filters SWC-107 to **write**-after-call:

| | write after call | read after call |
|---|---|---|
| `VulnerableVault` | yes, lines 23–24 | yes |
| `SafeVault` | **no** | yes, the assert at line 25 |

This mirrors Slither's own split between `reentrancy-eth` (a write that can
move ether) and `reentrancy-benign`. It is a configured filter, not a proven
exploit – which is consistent with the argument being made: neither Slither nor
Mythril can prove anything. Only the third column does that.

## Layout

```
contracts/          the pair
tools/              runners, merge, renderer
docker/smtchecker/  stock solc + Eldarica, because nothing ships both
fixtures/           committed known-good results, used as a fallback
.github/workflows/  build, publish to Pages, Slither SARIF to code scanning
out/                gitignored build output
```
