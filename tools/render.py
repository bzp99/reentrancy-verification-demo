#!/usr/bin/env python3
"""Render out/results.json into a single self-contained out/index.html.

_Authored by Claude Code_ - 2026-09-12, from verification-demo-plan.md section 7.

This module knows nothing about Docker, solvers, or Solidity semantics. It
reads the normalized document and writes a page, which is why the design can be
iterated in milliseconds without re-running a solver.

Two structural ideas carry the page:

1. The three verdicts are not three coloured badges, they are three different
   kinds of cell. `no_finding` is hollow - it should look like an absence,
   because that is exactly what it is - and `proved` is full. In the safe
   column two cells are visibly empty and one is visibly full, which is the
   argument, legible from the back of a room.

2. Source is syntax-highlighted and everything except the lines that matter is
   dimmed, so the eye lands on the moved statements before it reads anything.

Reading order is deliberate: the attack first, then what the tools say about
it, then the full contracts as reference material below the fold.
"""
import argparse
import base64
import html
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

# --------------------------------------------------------------------------
# Solidity highlighting
# --------------------------------------------------------------------------
# A small tokenizer rather than a library: the page must stay self-contained
# with no network dependency, and the grammar needed here is tiny.
#
# The colour choice is not arbitrary. Caller-controlled builtins (`msg`, `tx`,
# `this`) are set in the same oxblood as a violation, because on this page the
# attacker's reach is the subject.
SOL_RE = re.compile(r"""
    (?P<comment>//[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<number>\b\d+(?:\.\d+)*\b)
  | (?P<type>\b(?:u?int\d*|address|bool|bytes\d*|string|mapping)\b)
  | (?P<kw>\b(?:pragma|solidity|contract|interface|library|function|
        constructor|modifier|event|struct|enum|returns|return|external|public|
        internal|private|payable|view|pure|memory|storage|calldata|require|
        assert|revert|emit|if|else|for|while|do|break|continue|new|delete|
        using|is|override|virtual|unchecked|try|catch|immutable|constant)\b)
  | (?P<builtin>\b(?:msg|block|tx|this|abi|super)\b)
  | (?P<ident>\b[A-Za-z_$][\w$]*\b)
""", re.X)


def solidity(code):
    """Tokenize one line of Solidity into span-wrapped HTML."""
    out, pos, prev = [], 0, ""
    for m in SOL_RE.finditer(code):
        if m.start() > pos:
            out.append(html.escape(code[pos:m.start()]))
        kind, txt = m.lastgroup, html.escape(m.group())
        if kind == "ident":
            # The name straight after `function` is a definition, not a use.
            out.append(f'<span class="t-fn">{txt}</span>'
                       if prev == "function" else txt)
        else:
            out.append(f'<span class="t-{kind}">{txt}</span>')
        prev = m.group() if kind in ("kw", "type") else ""
        pos = m.end()
    out.append(html.escape(code[pos:]))
    return "".join(out)


def code_block(source, highlight, first=None, last=None, tone="", prop=None):
    """A syntax-highlighted listing with everything but the point dimmed.

    Two kinds of emphasis, and they mean different things: `highlight` bands
    the statements whose order is the bug, `prop` bands the assertion being
    checked. Red for the hazard, teal for the property, matching the verdict
    colours used in the table.

    Line numbers go in a data attribute and are drawn with ::before, so
    selecting the block copies code without the gutter.
    """
    hl, pl = set(highlight or []), set(prop or [])
    rows = []
    for n, ln in enumerate(source.splitlines(), 1):
        if (first and n < first) or (last and n > last):
            continue
        cls = "ln hl" if n in hl else "ln pl" if n in pl else "ln dim"
        rows.append(f'<span class="{cls}" data-n="{n}">'
                    f'{solidity(ln) or "&nbsp;"}</span>')
    return f'<pre class="code {tone}">' + "".join(rows) + "</pre>"


# --------------------------------------------------------------------------
# Presentation vocabulary
# --------------------------------------------------------------------------
GLYPH = {"violated": "✕", "proved": "∎", "no_finding": "○",
         "unknown": "?", "error": "!"}
# "COUNTEREXAMPLE FOUND" would overclaim: Slither pattern-matches and produces
# no counterexample at all, and Eldarica reports the violation site without
# concrete values. Only Mythril supplies a witness, which renders as its trace.
LABEL = {"violated": "VIOLATION FOUND", "proved": "PROVED SAFE",
         "no_finding": "NO FINDING", "unknown": "UNDECIDED",
         "error": "DID NOT RUN"}

CSS = """
:root{
--ground:#E6EBEF;--paper:#F6F8FA;--ink:#12171A;--dim:#39434B;
--rule:#C6CED5;--muted:#7F8C98;
--violated:#8C2F1E;--violated-soft:rgba(140,47,30,.09);
--proved:#12505F;--proved-soft:rgba(18,80,95,.09);
--syn-kw:#7A2E6B;--syn-type:#12505F;--syn-str:#6A5A1F;--syn-com:#94A0AB;
--syn-num:#6A5A1F;--syn-builtin:#8C2F1E;
--sp:28px}
*{box-sizing:border-box}
/* Coding fonts ligate => into one glyph and <= into an inequality sign. On a
   page whose purpose is showing exact Solidity, that is wrong. calt is the
   feature most coding fonts use for it. */
.mono,pre,code,.prop,.trace,.v-head,.ms,.ver,.qed,.cap,.hd small,footer,
.fact b,.stepn,.eyebrow{
font-variant-ligatures:none;font-feature-settings:"liga" 0,"clig" 0,"calt" 0}
html{scroll-behavior:smooth}
body{margin:0;background:var(--ground);color:var(--ink);
font-family:var(--sans);font-size:16px;line-height:1.5;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
/* Encodes the journey the page describes: violation on the left, proof on the
   right. */
.topbar{height:3px;background:linear-gradient(90deg,
var(--violated) 0%,var(--violated) 32%,#7A2E6B 50%,var(--proved) 72%,
var(--proved) 100%)}
.wrap{max-width:1260px;margin:0 auto;padding:10px 28px 64px}

.eyebrow{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;
text-transform:uppercase;color:var(--muted);margin-bottom:8px}
h1{font-size:28px;line-height:1.07;font-weight:650;margin:0 0 9px;
letter-spacing:-.022em}
h1 em{font-style:normal;color:var(--proved)}
.lede{color:var(--dim);margin:0;font-size:13.5px;line-height:1.45}

/* Three columns so the argument, the code and the attack all sit above the
   fold together with the verdict table. */
.hero{display:grid;grid-template-columns:minmax(272px,.84fr) 1.1fr 1.16fr;
gap:20px;align-items:stretch}
.hero>.lead{display:flex;flex-direction:column}
.panel{background:var(--paper);border:1px solid var(--rule)}
.ph{font-family:var(--mono);font-size:10px;letter-spacing:.13em;
text-transform:uppercase;color:var(--muted);padding:7px 13px;
border-bottom:1px solid var(--rule);display:flex;justify-content:space-between}
.ph b{font-weight:600;color:var(--violated)}

.steps{list-style:none;margin:0;padding:9px 14px 10px;flex:1}
.steps li{display:grid;grid-template-columns:20px 1fr;gap:10px;
padding:4px 0;font-size:12.5px;line-height:1.38;color:var(--dim);
border-top:1px solid var(--rule)}
.steps li:first-child{border-top:0}
.stepn{width:20px;height:20px;border:1px solid var(--violated);
color:var(--violated);border-radius:50%;font-size:10.5px;display:grid;
place-items:center;margin-top:1px}
.steps b{display:block;color:var(--ink);font-weight:600;font-size:13.5px;
margin-bottom:1px}
.steps code{font-family:var(--mono);font-size:11.5px;
background:var(--violated-soft);padding:0 3px;border-radius:2px}
.note{margin:0;padding:6px 13px;border-top:1px solid var(--rule);
font-size:11.5px;color:var(--muted);background:rgba(140,47,30,.05);
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.panel{display:flex;flex-direction:column}

/* Pinned to the bottom of the lead column so it lines up with the foot of
   the two panels beside it. */
.prop{margin-top:auto;padding-top:12px}
.prop .k{display:block;font-family:var(--mono);font-size:10px;
letter-spacing:.13em;text-transform:uppercase;color:var(--muted);
margin-bottom:6px}
.prop .v{display:block;font-family:var(--mono);font-size:12.5px;
background:var(--paper);border:1px solid var(--rule);padding:7px 11px;
border-left:3px solid var(--proved);overflow-x:auto}

/* code listings */
pre.code{font-family:var(--mono);font-size:12px;line-height:1.62;
margin:0;padding:12px 0;overflow-x:auto;background:transparent;border:0}
pre.code .ln{display:block;padding:0 14px 0 0;white-space:pre}
pre.code .ln::before{content:attr(data-n);display:inline-block;width:3.2em;
padding-right:1.1em;text-align:right;color:var(--muted);opacity:.55;
user-select:none;-webkit-user-select:none}
/* Dimmed by default so the eye lands on the point; hovering the listing
   brings the rest back for anyone who actually wants to read it. */
pre.code .dim{opacity:.42;transition:opacity .2s ease}
pre.code:hover .dim{opacity:.82}
pre.code .hl{background:var(--violated-soft);opacity:1;
box-shadow:inset 3px 0 0 var(--violated)}
pre.code.safe .hl{background:var(--proved-soft);
box-shadow:inset 3px 0 0 var(--proved)}
/* The assertion under test, in the same teal the proof uses. */
pre.code .pl{background:var(--proved-soft);opacity:1;
box-shadow:inset 3px 0 0 var(--proved)}
.t-comment{color:var(--syn-com);font-style:italic}
.t-kw{color:var(--syn-kw)}
.t-type{color:var(--syn-type)}
.t-string{color:var(--syn-str)}
.t-number{color:var(--syn-num)}
.t-builtin{color:var(--syn-builtin);font-weight:600}
.t-fn{color:var(--ink);font-weight:600}

/* verdict table */
.sec{display:flex;align-items:baseline;gap:12px;margin:10px 0 6px;
flex-wrap:wrap}
.sec h2{font-size:17px;font-weight:650;margin:0;letter-spacing:-.01em}
.sec p{margin:0;font-size:13.5px;color:var(--muted)}
.grid{display:grid;grid-template-columns:178px 1fr 1fr;gap:1px;
background:var(--rule);border:1px solid var(--rule)}
.grid>*{background:var(--paper);padding:7px 12px}
.hd{background:var(--ground);font-weight:650;font-size:14px;padding:7px 12px}
.hd small{display:block;font-weight:400;color:var(--muted);
font-family:var(--mono);font-size:11px;margin-top:2px;letter-spacing:.02em}
.toolcell{display:flex;flex-direction:column;justify-content:center}
.toolcell strong{font-size:15px}
.toolcell .tech{font-size:12.5px;color:var(--muted);margin-top:3px;
line-height:1.35}
.toolcell .ver{font-family:var(--mono);font-size:10.5px;color:var(--muted);
margin-top:6px;word-break:break-all;opacity:.8}
.cap{font-family:var(--mono);font-size:10px;margin-top:9px;
text-transform:uppercase;letter-spacing:.1em;display:inline-block;
padding:2px 6px;border:1px solid currentColor;align-self:flex-start}
.cap-yes{color:var(--proved)}
.cap-no{color:var(--muted);opacity:.75}

.v-head{font-family:var(--mono);font-size:12.5px;font-weight:650;
display:flex;gap:8px;align-items:center;letter-spacing:.06em}
.g{width:17px;height:17px;display:grid;place-items:center;font-size:11px;
border:1px solid currentColor;flex:none}
.v-violated{color:var(--violated)}
.v-proved{color:var(--proved)}
.v-no_finding,.v-unknown,.v-error{color:var(--muted)}
.cell-no_finding,.cell-unknown,.cell-error{
background:var(--paper) repeating-linear-gradient(135deg,transparent,
transparent 6px,rgba(127,140,152,.22) 6px,rgba(127,140,152,.22) 7px)}
.cell-proved{background:linear-gradient(180deg,var(--proved-soft),
rgba(18,80,95,.02)),var(--paper)}
/* The same left-edge banding the code listings use, so a cell and the line it
   is talking about are marked the same way. A hollow cell gets no band -
   there is nothing to point at. */
.cell-violated{box-shadow:inset 3px 0 0 var(--violated)}
.cell-proved{box-shadow:inset 3px 0 0 var(--proved)}
.grid>div[class^="cell-"]:hover{outline:1px solid var(--muted);
outline-offset:-1px}
.headline{font-size:13px;font-weight:600;margin-top:7px;color:var(--ink)}
.detail{font-size:12.5px;margin-top:3px;color:var(--dim);max-width:52ch;
line-height:1.4}
.facts{margin-top:8px;display:grid;grid-template-columns:auto 1fr;
gap:0 11px;font-size:11.5px;align-items:baseline;line-height:1.32}
.facts i{font-style:normal;color:var(--muted);font-family:var(--mono);
font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;
white-space:nowrap}
.fact b{font-weight:400;font-family:var(--mono);font-size:12px;
color:var(--dim);word-break:break-word}
.trace{font-family:var(--mono);font-size:11.5px;margin-top:8px;
border-left:2px solid var(--violated);padding:2px 0 2px 10px;color:var(--dim);
white-space:pre-wrap;overflow-x:auto;background:var(--violated-soft)}
.qed{font-family:var(--mono);font-size:12px;margin-top:9px;
color:var(--proved);border-top:1px solid rgba(18,80,95,.25);padding-top:8px;
display:flex;align-items:center;gap:8px}
.qed span{font-size:15px}
.ms{font-family:var(--mono);font-size:10.5px;color:var(--muted);
margin-left:auto;font-weight:400;letter-spacing:0}

/* below the fold */
.difference{margin-top:46px;padding-top:28px;border-top:1px solid var(--rule)}
.srcs{display:grid;grid-template-columns:1fr 1fr;gap:var(--sp);margin-top:14px}
.srcs .panel{overflow:hidden}
footer{margin-top:44px;border-top:1px solid var(--rule);padding-top:16px;
font-family:var(--mono);font-size:11.5px;color:var(--muted);
display:flex;flex-wrap:wrap;gap:20px}
a{color:inherit}

@media (max-width:980px){
.hero,.srcs,.grid{grid-template-columns:1fr}
.hd{border-top:1px solid var(--rule)}}

/* Keeping the verdict table above the fold is the whole point of the layout,
   and a projector is rarely the height of the laptop it was designed on. These
   shrink the rhythm rather than letting the last row fall off the screen. */
/* 1030 rather than 940: the uncompressed layout needs about 1020px of
   viewport, so anything below that takes the tighter rhythm. A lower
   threshold leaves a dead band where the last row falls just off screen. */
@media (max-height:1030px){
.wrap{padding-top:8px}
h1{font-size:25px;margin-bottom:7px}
.lede{font-size:12.5px}
.prop{padding-top:9px}
.prop .v{font-size:11.5px;padding:6px 10px}
.ph{padding:5px 12px}
pre.code{font-size:10.5px;line-height:1.5;padding:8px 0}
.steps{padding:7px 13px 8px}
.steps li{font-size:11.5px;padding:3px 0}
.steps b{font-size:12.5px}
.note{padding:5px 13px;font-size:11px}
.sec{margin:8px 0 6px}.sec h2{font-size:16px}
.grid>*{padding:6px 11px}
.hd{padding:6px 11px;font-size:13.5px}
.v-head{font-size:12px}
.headline{font-size:12.5px;margin-top:6px}
.detail{font-size:12px;line-height:1.36}
.facts{font-size:10.5px;line-height:1.28;margin-top:7px}
.toolcell .tech{font-size:11.5px}
.cap{margin-top:6px}
.trace{font-size:10.5px;margin-top:6px}
.qed{margin-top:7px;padding-top:6px;font-size:11.5px}}

/* Likewise: the mid layout needs about 900px, so the aggressive rhythm has to
   start just above that rather than at 820. */
@media (max-height:910px){
.eyebrow{display:none}
h1{font-size:22px;margin-bottom:6px}
.lede{font-size:12px}
pre.code{font-size:10px;line-height:1.5}
.steps li{font-size:11.5px}
.steps b{font-size:12.5px}
.headline{font-size:12px}
.detail{font-size:11.5px}
.facts{font-size:10.5px}
.toolcell .tech{font-size:11.5px}
.sec{margin:8px 0 5px}.sec h2{font-size:15px}}

/* Entrance: a short stagger, and nothing at all if motion is unwelcome. */
@media (prefers-reduced-motion:no-preference){
.rise{opacity:0;transform:translateY(9px);
animation:rise .42s cubic-bezier(.22,.61,.36,1) forwards;
animation-delay:calc(var(--i,0)*45ms)}
@keyframes rise{to{opacity:1;transform:none}}}

@media print{.topbar{display:none}body{background:#fff}
.rise{opacity:1;transform:none;animation:none}
pre.code .dim{opacity:.75}}

::selection{background:rgba(140,47,30,.16)}
:focus-visible{outline:2px solid var(--proved);outline-offset:2px}
.panel{transition:border-color .2s ease}
.panel:hover{border-color:var(--muted)}
"""


AUTOFIT_JS = """
/* Keep the verdict table above the fold on whatever screen this is shown on.
   The CSS height breakpoints get close; this closes the gap exactly, because
   a projector is never quite the height you tuned for. `zoom` reflows rather
   than merely painting smaller, so one measure-and-set pass converges.
   Progressive enhancement: without JS the breakpoints still apply. */
(function () {
  var fold = document.querySelector('.fold');
  var grid = document.querySelector('.grid');
  if (!fold || !grid) return;
  var MIN = 0.68, PAD = 10;
  function fit() {
    fold.style.zoom = '1';
    var bottom = grid.getBoundingClientRect().bottom;
    var avail = window.innerHeight - PAD;
    if (bottom > avail) fold.style.zoom = Math.max(MIN, avail / bottom);
  }
  fit();
  var t;
  addEventListener('resize', function () {
    clearTimeout(t);
    t = setTimeout(fit, 120);
  });
})();
"""


def duration(ms):
    """Sub-second runs read better in ms; a five-minute one does not."""
    if ms < 1000:
        return f"{ms} ms"
    if ms < 90000:
        return f"{ms / 1000:.1f} s"
    return f"{int(ms // 60000)} min {int(ms % 60000 // 1000)} s"


def short_version(v):
    """`0.8.26+commit.8a97fa7a.Linux.g++` -> `0.8.26`.

    The build metadata wraps to a second line in a 178px column and earns
    none of that space; the full string stays in the title and the footer.
    """
    return str(v).split("+")[0].strip() or str(v)


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
    faces.append(f":root{{--sans:{sans}ui-sans-serif,system-ui,"
                 f"-apple-system,'Segoe UI',Roboto,sans-serif;"
                 f"--mono:{mono}ui-monospace,'SF Mono',Menlo,Consolas,"
                 f"monospace}}")
    return "\n".join(faces)


def cell(res):
    v = res["verdict"]
    # A hollow cell carries no visible prose, but the analysis did say
    # something - keep it reachable rather than throwing it away.
    tip = ""
    if v == "no_finding":
        note = " ".join(x for x in (res.get("headline"), res.get("detail")) if x)
        if note:
            tip = f' title="{html.escape(note, quote=True)}"'

    parts = [f'<div class="v-head v-{v}"><span class="g">{GLYPH[v]}</span>'
             f'<span>{LABEL[v]}</span>'
             f'<span class="ms">{duration(res["duration_ms"])}</span></div>']

    if v != "no_finding":
        if res.get("headline"):
            parts.append(f'<div class="headline">'
                         f'{html.escape(res["headline"])}</div>')
        if res.get("detail"):
            parts.append(f'<div class="detail">'
                         f'{html.escape(res["detail"])}</div>')
        if res.get("facts"):
            rows = "".join(
                f'<i>{html.escape(str(k))}</i>'
                f'<span class="fact"><b>{html.escape(str(val))}</b></span>'
                for k, val in res["facts"])
            parts.append(f'<div class="facts">{rows}</div>')
    if res.get("trace"):
        parts.append('<div class="trace">'
                     + html.escape("\n".join(res["trace"])) + "</div>")
    if v == "proved":
        parts.append('<div class="qed"><span>∎</span>'
                     '<em style="font-style:normal">Every reachable state, '
                     'unbounded depth.</em></div>')
    return f'<div class="cell-{v}"{tip}>' + "".join(parts) + "</div>"


def hero(d):
    """The attack, before any tool has an opinion about it."""
    vuln = next(c for c in d["cases"] if c["id"] == "vulnerable")
    first, last = vuln.get("excerpt", [1, 40])

    steps = "".join(
        # Step text is authored content from merge.py, not tool output, so its
        # inline <code>/<em> markup is intentional and passes through.
        f'<li><span class="stepn">{n}</span>'
        f'<span><b>{html.escape(title)}</b>{body}</span></li>'
        for n, (title, body) in enumerate(d.get("exploit", []), 1))

    note = (f'<p class="note">{d["exploit_note"]}</p>'
            if d.get("exploit_note") else "")

    n_steps = len(d.get("exploit", []))
    return f"""<section class="hero">
<div class="lead rise" style="--i:0">
  <div class="eyebrow">Reentrancy · Solidity 0.8.26</div>
  <h1>Two lines apart. Only one tool can <em>prove</em> it.</h1>
  <p class="lede">The withdrawal pattern that drained the DAO, and its
  checks-effects-interactions fix – checked on every commit by a static
  analyser, a symbolic executor and a model checker.</p>
  <div class="prop"><span class="k">the property, in both contracts</span>
  <span class="v">{solidity(d["property"])}</span></div>
</div>
<div class="panel rise" style="--i:1">
  <div class="ph"><span>contracts/VulnerableVault.sol</span>
  <b>withdraw()</b></div>
  {code_block(vuln["source"], vuln["highlight_lines"], first, last,
              prop=[vuln.get("property_line")])}
</div>
<div class="panel rise" style="--i:2">
  <div class="ph"><span>how it is drained</span><b>{n_steps} steps</b></div>
  <ol class="steps">{steps}</ol>
  {note}
</div>
</section>"""


def render(d):
    cases = d["cases"]

    g = ['<div class="hd">Tool</div>']
    for c in cases:
        g.append(f'<div class="hd">{html.escape(c["title"])}'
                 f'<small>{html.escape(c["subtitle"])}</small></div>')
    for t in d["tools"]:
        cap = ('<div class="cap cap-yes">can prove</div>' if t.get("can_prove")
               else '<div class="cap cap-no">cannot prove</div>')
        g.append(f'<div class="toolcell"><strong>'
                 f'{html.escape(t["name"])}</strong>'
                 f'<div class="tech">{html.escape(t["technique"])}</div>'
                 f'<div class="ver" title="{html.escape(str(t["version"]), quote=True)}">'
                 f'{html.escape(short_version(t["version"]))}</div>'
                 f'{cap}</div>')
        for c in cases:
            g.append(cell(t["results"][c["id"]]))

    srcs = "".join(
        f'<div class="panel"><div class="ph">'
        f'<span>{html.escape(c["file"])}</span>'
        f'<b>{html.escape(c["subtitle"])}</b></div>'
        f'{code_block(c["source"], c["highlight_lines"], prop=[c.get("property_line")], tone=("safe" if c["id"] == "safe" else ""))}'
        f'</div>' for c in cases)

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
<style>{fonts_css()}{CSS}</style></head><body>
<div class="topbar"></div><div class="wrap">

<div class="fold">
{hero(d)}

<div class="sec"><h2>What three analyses say</h2>
<p>All three catch the bug. Only one can certify the fix.</p></div>
<div class="grid rise" style="--i:3">{"".join(g)}</div>
</div>

<section class="difference"><div class="sec"><h2>The difference</h2>
<p>Same contract, same assertion – the two writes moved above the call.</p></div>
<div class="srcs">{srcs}</div></section>

<footer><span>generated {html.escape(d["generated_at"])}</span>
<span>commit {commit}</span>
<span>{versions}</span>
</footer></div>
<script>{AUTOFIT_JS}</script>
</body></html>"""


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
