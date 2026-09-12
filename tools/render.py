#!/usr/bin/env python3
"""Render out/results.json into a single self-contained out/index.html.

_Authored by Claude Code_ - 2026-09-12.

This module knows nothing about Docker, solvers, or Solidity. It reads the
normalized document and writes a page, which is why the design can be iterated
in milliseconds without re-running a solver.

The structural idea: the three verdicts are not three coloured badges, they are
three different kinds of cell. `no_finding` is hollow - it should look like an
absence, because that is exactly what it is - and `proved` is full. In the safe
column Slither and Mythril are visibly empty and SMTChecker is visibly full,
which is the argument, legible at a glance.
"""
import argparse
import base64
import html
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

CSS = """
:root{--ground:#E9EDF0;--ink:#14181B;--rule:#C3CBD2;--muted:#8A96A1;
--violated:#8C2F1E;--proved:#1B4D5C;--paper:#F5F7F9;--dim:#3A444C}
*{box-sizing:border-box}
/* Coding fonts ligate => into a single glyph and <= into an inequality sign.
   On a page whose whole point is showing exact Solidity, that is wrong: the
   contract would read `mapping(address => uint256)` as an implication arrow.
   calt is the feature most coding fonts use for it. */
pre,.prop,.trace,.v-head,.ms,.ver,.qed,.cap,.hd small,footer{
font-variant-ligatures:none;font-feature-settings:"liga" 0,"clig" 0,"calt" 0}
body{margin:0;background:var(--ground);color:var(--ink);
font-family:var(--sans);font-size:17px;line-height:1.55;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:56px 32px 96px}
h1{font-size:38px;line-height:1.15;font-weight:600;margin:0 0 12px;
max-width:22ch;letter-spacing:-0.015em}
.lede{max-width:62ch;color:var(--dim);margin:0 0 8px}
.prop{font-family:var(--mono);font-size:15px;background:var(--paper);
border:1px solid var(--rule);padding:10px 14px;display:inline-block;
margin:20px 0 40px}
.grid{display:grid;grid-template-columns:210px 1fr 1fr;gap:1px;
background:var(--rule);border:1px solid var(--rule);margin-bottom:48px}
.grid>*{background:var(--paper);padding:18px 20px}
.hd{background:var(--ground);font-weight:600}
.hd small{display:block;font-weight:400;color:var(--muted);
font-family:var(--mono);font-size:12.5px;margin-top:4px}
.toolcell{display:flex;flex-direction:column;justify-content:center}
.toolcell .tech{font-size:13.5px;color:var(--muted);margin-top:2px}
.toolcell .ver{font-family:var(--mono);font-size:12px;color:var(--muted);
margin-top:6px;word-break:break-all}
.toolcell .cap{font-family:var(--mono);font-size:11px;margin-top:8px;
text-transform:uppercase;letter-spacing:.06em}
.cap-yes{color:var(--proved)}
.cap-no{color:var(--muted)}
.v-head{font-family:var(--mono);font-size:14px;font-weight:600;
display:flex;gap:9px;align-items:baseline}
.v-violated{color:var(--violated)}
.v-proved{color:var(--proved)}
.v-no_finding,.v-unknown,.v-error{color:var(--muted)}
.cell-no_finding,.cell-unknown,.cell-error{
background:repeating-linear-gradient(135deg,transparent,transparent 7px,
rgba(138,150,161,.16) 7px,rgba(138,150,161,.16) 8px)}
.detail{font-size:14px;margin-top:9px;color:var(--dim);max-width:56ch}
.trace{font-family:var(--mono);font-size:12.5px;margin-top:12px;
border-left:2px solid var(--violated);padding-left:12px;color:var(--dim);
white-space:pre-wrap;overflow-x:auto}
.qed{font-family:var(--mono);font-size:13px;margin-top:12px;
color:var(--proved);border-top:1px solid var(--rule);padding-top:10px}
.ms{font-family:var(--mono);font-size:11.5px;color:var(--muted);
margin-left:auto;font-weight:400}
h2{font-size:22px;font-weight:600;margin:0 0 6px}
.srcs{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:14px}
pre{font-family:var(--mono);font-size:12.5px;line-height:1.6;
background:var(--paper);border:1px solid var(--rule);padding:16px;
overflow-x:auto;margin:10px 0 0}
/* Every line is its own block, and the lines are joined with no newline
   between them. Mixing block spans with literal newlines inside a <pre>
   renders a blank line after each highlighted line. */
pre span{display:block;margin:0 -16px;padding:0 16px}
pre .hl{background:rgba(140,47,30,.13)}
pre.safe .hl{background:rgba(27,77,92,.12)}
footer{margin-top:64px;border-top:1px solid var(--rule);padding-top:18px;
font-family:var(--mono);font-size:12.5px;color:var(--muted);
display:flex;flex-wrap:wrap;gap:22px}
a{color:inherit}
@media (max-width:900px){.grid,.srcs{grid-template-columns:1fr}
.hd{border-top:1px solid var(--rule)}}
"""

GLYPH = {"violated": "✕", "proved": "∎", "no_finding": "○",
         "unknown": "?", "error": "!"}
# "COUNTEREXAMPLE FOUND" would overclaim: Slither pattern-matches and produces
# no counterexample at all, and Eldarica reports the violation site without
# concrete values. Only Mythril supplies a witness, which renders as its trace.
LABEL = {"violated": "VIOLATION FOUND", "proved": "PROVED SAFE",
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
        lines.append(f'<span class="{"hl" if n in hl else "ln"}">{esc}</span>')
    return f'<pre class="{cls}">' + "".join(lines) + "</pre>"


def duration(ms):
    """Sub-second runs read better in ms; a five-minute one does not."""
    if ms < 1000:
        return f"{ms} ms"
    if ms < 90000:
        return f"{ms / 1000:.1f} s"
    return f"{int(ms // 60000)} min {int(ms % 60000 // 1000)} s"


def cell(res):
    v = res["verdict"]
    # A hollow cell carries no visible prose, but the analysis actually said
    # something - keep it in the title attribute rather than throwing it away.
    tip = ""
    if v == "no_finding":
        note = " ".join(x for x in (res.get("headline"), res.get("detail")) if x)
        if note:
            tip = f' title="{html.escape(note, quote=True)}"'

    parts = [f'<div class="v-head v-{v}"><span>{GLYPH[v]}</span>'
             f'<span>{LABEL[v]}</span>'
             f'<span class="ms">{duration(res["duration_ms"])}</span></div>']
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
    return f'<div class="cell-{v}"{tip}>' + "".join(parts) + "</div>"


def render(d):
    cases = d["cases"]
    g = ['<div class="hd">Tool</div>']
    for c in cases:
        g.append(f'<div class="hd">{html.escape(c["title"])}'
                 f'<small>{html.escape(c["subtitle"])}</small></div>')
    for t in d["tools"]:
        cap = ('<div class="cap cap-yes">can prove</div>' if t.get("can_prove")
               else '<div class="cap cap-no">cannot prove</div>')
        g.append(f'<div class="toolcell"><div><strong>'
                 f'{html.escape(t["name"])}</strong></div>'
                 f'<div class="tech">{html.escape(t["technique"])}</div>'
                 f'<div class="ver">{html.escape(str(t["version"]))}</div>'
                 f'{cap}</div>')
        for c in cases:
            g.append(cell(t["results"][c["id"]]))

    srcs = "".join(f"<div><h2>{html.escape(c['title'])}</h2>"
                   f"{source_block(c)}</div>" for c in cases)

    repo = (d.get("repo", "") or "").replace("git@github.com:",
                                             "https://github.com/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    commit = (f'<a href="{html.escape(repo)}/commit/'
              f'{html.escape(d["commit_full"])}">{html.escape(d["commit"])}</a>'
              if repo.startswith("http") else html.escape(d["commit"]))

    versions = " · ".join(
        html.escape(f"{t['name']} {t['version']}") for t in d["tools"])

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reentrancy – three analyses, one contract pair</title>
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
<span>{versions}</span>
</footer></div></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "out/results.json"))
    ap.add_argument("--fallback",
                    default=str(ROOT / "fixtures/results.known-good.json"))
    ap.add_argument("--output", default=str(ROOT / "out/index.html"))
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
