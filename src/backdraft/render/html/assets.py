"""Static assets: the stylesheet, the behavior script, the mark, the favicon.

The strings are the artifact's entire presentation layer, inlined at render —
the CSP (`default-src 'none'`) forbids fetching them, so they can have no
other home. The script's `fmtCell` mirrors `fmt.fmt_cell` deliberately; the
parity tests hold the pair together.

`STYLESHEET` and `SCRIPT` are the authored sources; the artifact ships
`STYLESHEET_MIN` and `SCRIPT_MIN`, the same bytes through `_minify` — a
whitespace-and-comments pass only. Lines are never joined (the script relies
on newlines for statement ends) and nothing is renamed: the minified script
must still be readable in view-source, greppable by the parity tests, and
byte-deterministic across runs.
"""

from __future__ import annotations

import urllib.parse


def _minify(source: str) -> str:
    """Strip comments, per-line indentation, and blank lines. Nothing else.

    Deliberately line-based and lexically timid: a `/*` opens a comment only
    at the start of a line (nothing in either asset embeds one mid-line, and
    a string or regex containing the pair would defeat a cleverer scanner),
    and newlines all survive, so JS semicolon insertion is undisturbed.
    """
    out: list[str] = []
    in_comment = False
    for line in source.splitlines():
        text = line.strip()
        while True:
            if in_comment:
                end = text.find("*/")
                if end == -1:
                    text = ""
                    break
                text = text[end + 2:].lstrip()
                in_comment = False
            elif text.startswith("/*"):
                end = text.find("*/", 2)
                if end == -1:
                    in_comment = True
                    text = ""
                    break
                text = text[end + 2:].lstrip()
            else:
                break
        if text:
            out.append(text)
    return "\n".join(out)

FLAME_PATH = (
    "M44 3 C38 8 30 10 26 16 C23.5 20 24.5 24 27 26.5 "
    "C20.5 28 14.5 33 14 41 C13.3 51.5 22 59.5 33 59.5 "
    "C44 59.5 51.5 51.5 51 41.5 C50.6 33.5 45 29 42.5 22.5 "
    "C40.8 18 42.5 9 44 3 Z "
    "M34 34 C38 38.5 39.5 43.5 37.5 47.5 C35 52 28.5 51.5 26.5 47 "
    "C25 43.5 27.5 40 30 38.5 C31.8 37.5 33.2 36 34 34 Z"
)
"""The backdraft mark: a flame swept backward by returning air. The canonical
vector is `assets/backdraft-mark.svg`; this is its in-code copy for the favicon
and the sign-off."""


def _favicon() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="13" fill="#FBFAF6"/>'
        '<g transform="translate(32 32) scale(0.82) translate(-32 -32)">'
        f'<path fill="#282828" fill-rule="evenodd" d="{FLAME_PATH}"/></g></svg>'
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg)


STYLESHEET = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --paper:#FFFFFF; --ink:#282828; --muted:#676767; --faint:#A3A19A;
  --hover:rgba(40,40,40,.05); --active:rgba(40,40,40,.09);
  --underline:rgba(40,40,40,.16);
  --hairline:#E8E5DD; --hairline-strong:#D6D2C6;
  --notebook:#FBFAF6; --notebook-line:rgba(40,40,40,.05);
  --sel:#1F7244; --sel-soft:#EAF3EE;
  --excel-line:#E3E2DC; --excel-head:#F4F3EE;
  --hl:#F5E6AE;
  --alarm:#A63A2E;
  --serif:'Iowan Old Style','Iowan Old Style BT',Palatino,'Palatino Linotype',Georgia,serif;
  --sans:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Helvetica,sans-serif;
  --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  --rail-w:calc(50vw - 14px);
}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--notebook);color:var(--ink);
  font-family:var(--serif);font-size:17px;line-height:1.6;
  font-synthesis:none;text-rendering:optimizeLegibility}
.frame{display:grid;grid-template-columns:minmax(0,1fr) 28px var(--rail-w)}
.pagecol{grid-column:1;min-width:0;max-width:44rem;width:100%;
  padding:4rem 2.75rem 6rem;margin:0 auto}
.divider{grid-column:2;cursor:col-resize;touch-action:none}
.divider::before{content:'';display:block;position:sticky;top:12.5vh;height:75vh;
  width:1px;margin:0 auto;background:var(--hairline-strong);transition:background .15s}
.divider:hover::before,.divider.dragging::before{background:var(--ink);width:2px}
.railcol{grid-column:3;min-width:0;
  background:
    repeating-linear-gradient(0deg,var(--notebook-line) 0 1px,transparent 1px 18px),
    repeating-linear-gradient(90deg,var(--notebook-line) 0 1px,transparent 1px 18px),
    var(--notebook)}
.rail{position:sticky;top:0;max-height:100vh;overflow-y:auto;
  font-family:var(--sans);font-size:.84rem;line-height:1.55;
  padding:2.5rem 2.25rem}
a{color:inherit}

/* ---- masthead ---- */
.masthead{margin:0 0 3rem;text-align:center}
.masthead h1{font-size:1.85rem;line-height:1.35;margin:0 0 .55rem;font-weight:600}
.subtitle{font-family:var(--serif);font-size:.95rem;color:var(--muted);margin:0}
.alarmline{font-family:var(--sans);font-size:.78rem;color:var(--alarm);
  margin:.6rem 0 0}

/* ---- the document ---- */
.doc h1{display:none}
.doc h2{font-family:var(--serif);font-size:1.2rem;font-weight:600;
  margin:2.3rem 0 .7rem}
.doc p{margin:0 0 1.05rem}
.doc ul,.doc ol{margin:0 0 1.05rem;padding-left:1.4rem}
.doc blockquote{margin:1.1rem 0;padding:.1rem 0 .1rem 1rem;
  border-left:2px solid var(--hairline);color:var(--muted)}
.doc pre{font-family:var(--mono);font-size:.78rem;line-height:1.5;overflow-x:auto;
  background:var(--paper);border:1px solid var(--hairline);border-radius:3px;
  padding:.8rem .95rem;margin:0 0 1.05rem}
.doc code{font-family:var(--mono);font-size:.85em}
.table-wrap{overflow-x:auto;margin:0 0 1.1rem}
.doc table{border-collapse:collapse;font-family:var(--sans);font-size:.84rem}
.doc th,.doc td{padding:.35rem .65rem;border-bottom:1px solid var(--hairline);
  text-align:left}
.doc .t-right{text-align:right}
.doc .t-center{text-align:center}
.bd-image{color:var(--muted);font-style:italic}
.claim{color:inherit;cursor:pointer;
  text-decoration:underline;text-decoration-color:var(--underline);
  text-decoration-thickness:1px;text-underline-offset:3px;
  transition:background-color .15s,text-decoration-color .15s}
.claim:hover{background:var(--hover);text-decoration-color:var(--ink)}
.claim.active{background:var(--active);text-decoration-color:var(--ink)}
.claim.flagged{text-decoration-style:wavy;text-decoration-color:var(--alarm)}
.mark{font-family:var(--sans);font-size:.58em;font-weight:600;color:var(--muted);
  margin-left:.14em}
.claim:hover .mark,.claim.active .mark{color:var(--ink)}
.claim.flagged .mark{color:var(--alarm)}

/* ---- rail resting ---- */
.resting{background:var(--paper);border:1px solid var(--hairline);border-radius:3px;
  padding:1.2rem 1.35rem;box-shadow:0 1px 3px rgba(40,40,40,.05)}
.resting h2{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
  margin:0 0 .9rem;color:var(--faint);font-weight:600}
.resting ul{list-style:none;margin:0;padding:0}
.resting li{margin:.75rem 0}
.resting .doc{display:block;color:var(--ink);font-weight:600;font-size:.84rem}
.resting .filemeta{display:block;font-size:.72rem;color:var(--muted);
  overflow-wrap:anywhere;margin-top:.15rem}
.resting .hint{margin:1.2rem 0 0;font-size:.74rem;color:var(--muted);line-height:1.5}

/* ---- the card ---- */
.card{background:var(--paper);border:1px solid var(--hairline);border-radius:3px;
  box-shadow:0 1px 3px rgba(40,40,40,.05),0 8px 24px rgba(40,40,40,.06);
  padding:1.05rem 1.35rem 1.15rem;animation:rise .16s ease;
  resize:vertical;overflow:auto;min-height:12rem;max-height:82vh}
@keyframes rise{from{opacity:0;transform:translateY(.35rem)}to{opacity:1;transform:none}}

/* the card owns its height; its contents divide it. The header, the source
   selector, the source line and the tabs are fixed rows — they are how you
   know what you are looking at, so they never scroll away. Everything below
   them is a viewport onto the evidence, and it takes whatever the fixed rows
   left: drag the card taller and the evidence grows, drag it short and the
   evidence scrolls inside itself. Nothing here may carry a fixed height —
   that was the old bug, a quote pinned at 15rem inside a card twice as tall.
   The two rows that are toggled — `.cite.on` and `.pane.on` — carry their own
   share of this below, where `display` is decided. */
.card{display:flex;flex-direction:column}
/* an author `display` outranks the UA sheet's `[hidden]{display:none}`, so
   the card has to hide itself once it declares one */
.card[hidden]{display:none}
.card>header,.card>.srccount,.card>.srcsel,.cite>.src,.cite>.alarm,
.tabs{flex:0 0 auto}
/* the quote, the drift diff and the record keep their own height, capped at a
   share of the card rather than at a fixed rem: the cap tracks the drag, and
   none of the three is ever clipped mid-line to make room for the evidence */
.card .quote,.card .drift,.card .record{flex:0 0 auto;max-height:40%;overflow:auto}
/* 5rem is a floor, not a size: the evidence is the point of the card and never
   shrinks away to nothing, so at the card's minimum height it keeps this much
   and the citation scrolls instead */
.evidence{display:flex;flex-direction:column;flex:1 1 auto;min-height:5rem}
.pagetext,.rawtext{flex:1 1 auto;min-height:0;overflow:auto}
.cite>.pagetext,.cite>.rawtext{min-height:5rem}
.grid{display:flex;flex-direction:column;flex:1 1 auto;min-height:0}
.grid .gridwrap{flex:1 1 auto;min-height:0}
/* the page image is a picture at a fixed scale: the pane scrolls over it
   rather than shrinking it past reading size */
.plate:not(.grid){flex:0 0 auto}

.card header{display:flex;align-items:baseline;justify-content:space-between;
  padding:0 0 .2rem}
.cardno{font-family:var(--sans);font-size:.74rem;font-weight:600;color:var(--ink);
  letter-spacing:.02em}
.close{background:none;border:0;font-size:1.05rem;line-height:1;color:var(--faint);
  cursor:pointer;padding:.1rem .3rem}
.close:hover{color:var(--ink)}

/* source selector */
.srccount{font-family:var(--sans);font-size:.68rem;color:var(--faint);
  margin:.1rem 0 0}
.srcsel{display:flex;gap:1.3rem;border-bottom:1px solid var(--hairline);
  margin:.3rem 0 .95rem}
.srcsel button{font-family:var(--sans);font-size:.76rem;font-weight:500;
  color:var(--muted);background:none;border:0;padding:.45rem 0;cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-1px;letter-spacing:.01em}
.srcsel button:hover{color:var(--ink)}
.srcsel button.on{color:var(--ink);font-weight:600;border-bottom-color:var(--ink)}
.srcsel button.on.excel{border-bottom-color:var(--sel)}
.srcsel button.on.pdf{border-bottom-color:#9E3B2F}

.cite{display:none;padding:.15rem 0}
.cite.on{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;overflow:auto}
.src{margin:.2rem 0 .6rem;display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap}
.src .doc{font-weight:600;color:var(--ink);font-size:.88rem}
.src .loc{font-size:.72rem;color:var(--faint)}
.alarm{color:var(--alarm);font-size:.78rem;margin:.35rem 0}

.quote{margin:.35rem 0 .75rem;padding:.05rem 0 .05rem .9rem;
  border-left:2px solid var(--hairline-strong);font-family:var(--serif);
  font-size:.9rem;line-height:1.55;color:var(--ink);overflow-y:auto}
.quote p{margin:0 0 .5rem}.quote p:last-child{margin:0}
.quote h1,.quote h2,.quote h3,.quote h4{font-family:var(--sans);font-size:.64rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--faint);
  margin:.6rem 0 .3rem;font-weight:600}
.quote ul,.quote ol{margin:.2rem 0 .5rem;padding-left:1.2rem}
.quote strong{font-weight:600}
.quote .bd-image{display:none}

/* drift: the two snippets, word-diffed */
.drift{margin:.5rem 0 .7rem;font-size:.84rem}
.drift-row{display:flex;gap:.6rem;margin:.3rem 0}
.drift-row span{flex:0 0 3.6rem;font-family:var(--sans);font-size:.6rem;
  color:var(--faint);text-transform:uppercase;letter-spacing:.08em;padding-top:.2rem}
.drift-row p{margin:0;font-family:var(--serif);overflow-wrap:anywhere}
.drift del{text-decoration:line-through;text-decoration-thickness:1px;
  color:var(--alarm);background:rgba(166,58,46,.08)}
.drift ins{text-decoration:none;color:var(--sel);background:var(--sel-soft)}

/* view toggle */
.evidence{margin:.4rem 0 .3rem}
.tabs{display:flex;gap:.9rem;margin-bottom:.55rem}
.tab{font-family:var(--sans);font-size:.68rem;font-weight:500;color:var(--faint);
  background:none;border:0;padding:.15rem 0;cursor:pointer;
  border-bottom:1px solid transparent}
.tab:hover{color:var(--ink)}
.tab.on{color:var(--ink);border-bottom-color:var(--ink)}
.pane{display:none}
.pane.on{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;overflow:auto}
.pagetext,.rawtext{border:1px solid var(--hairline);
  border-radius:2px;padding:.7rem .85rem;background:var(--paper)}
.pagetext{font-family:var(--serif);font-size:.86rem;line-height:1.55}
.pagetext h1,.pagetext h2,.pagetext h3{font-family:var(--sans);font-size:.64rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--faint);
  margin:.7rem 0 .35rem;font-weight:600}
.pagetext h1:first-child,.pagetext h2:first-child{margin-top:0}
.pagetext p{margin:0 0 .5rem}
.pagetext ul{margin:.2rem 0 .5rem;padding-left:1.2rem}
.pagetext .table-wrap{overflow-x:auto;margin:.4rem 0}
.pagetext table{border-collapse:collapse;font-family:var(--sans);font-size:.7rem;
  white-space:nowrap}
.pagetext th,.pagetext td{border:1px solid var(--hairline);padding:.2rem .5rem;
  text-align:left}
.pagetext th{background:var(--excel-head);font-weight:600}
.rawtext{font-family:var(--mono);font-size:.68rem;line-height:1.5;white-space:pre-wrap;
  overflow-wrap:anywhere;color:var(--ink);margin:.4rem 0}

/* evidence plates */
.plate{margin:.1rem 0 .3rem;cursor:zoom-in}
.plate img{display:block;width:100%;height:auto;border:1px solid var(--hairline);
  border-radius:2px;background:#fff}
.plate:hover img{border-color:var(--hairline-strong)}
.plate figcaption{font-family:var(--sans);font-size:.68rem;color:var(--muted);
  margin-top:.4rem;display:flex;justify-content:space-between;gap:.6rem}
.hintcap{color:var(--ink);opacity:0;transition:opacity .15s;white-space:nowrap}
.plate:hover .hintcap{opacity:.7}

/* the excel experience */
.grid{cursor:pointer}
.grid .gridwrap{overflow:auto;border:1px solid var(--excel-line);border-radius:2px;
  background:var(--paper)}
.grid table,.sheettable{border-collapse:separate;border-spacing:0;
  font-family:var(--sans);font-size:.72rem;line-height:1.6;min-width:100%;
  font-variant-numeric:tabular-nums}
.grid th,.sheettable th{font-weight:500;color:#6B6B66;background:var(--excel-head);
  padding:.1rem .55rem;text-align:center;
  border-bottom:1px solid var(--excel-line);border-right:1px solid var(--excel-line);
  font-size:.66rem}
.grid td,.sheettable td{padding:.1rem .55rem;
  border-bottom:1px solid var(--excel-line);border-right:1px solid var(--excel-line);
  white-space:nowrap;max-width:14rem;overflow:hidden;text-overflow:ellipsis;
  background:var(--paper);text-align:left}
.grid td.num,.sheettable td.num{text-align:right}
.grid td.cited,.sheettable td.cited{background:var(--sel-soft);
  box-shadow:inset 0 0 0 2px var(--sel);font-weight:600}
/* both sheet views scroll under their own headers — the card's window since
   it flexes with the card, the overlay's since it always did */
.grid thead th,.sheettable thead th{position:sticky;top:0;z-index:2}
.grid tbody th,.sheettable tbody th{position:sticky;left:0;z-index:1}
.grid thead th:first-child,.sheettable thead th:first-child{left:0;z-index:3}
tr.citedrow th{background:var(--sel-soft);color:var(--sel);font-weight:600}
th.citedcol{background:var(--sel-soft);color:var(--sel);font-weight:600}

/* the record layer */
.record{margin:.5rem 0 .1rem;font-size:.7rem}
.record summary{cursor:pointer;color:var(--faint);letter-spacing:.1em;
  text-transform:uppercase;font-size:.6rem;font-weight:600;list-style:none}
.record summary::before{content:'\\25B8';margin-right:.35rem;font-size:.55rem}
.record[open] summary::before{content:'\\25BE'}
.record[open] summary{margin-bottom:.35rem}
.rr{display:flex;gap:.55rem;margin:.22rem 0;color:var(--muted);overflow-wrap:anywhere}
.rr span{flex:0 0 4.4rem;text-transform:uppercase;letter-spacing:.08em;font-size:.58rem;
  padding-top:.1rem}
.rr code{font-family:var(--mono);font-size:.66rem;color:var(--ink)}
.rr.verdict code{text-transform:uppercase;letter-spacing:.05em}
.v-fail code{color:var(--alarm)} .v-partial code{color:#96690F}
.v-skip code{color:var(--faint)}

/* ---- end matter ---- */
.endmatter{margin-top:4rem;border-top:1px solid var(--hairline);padding-top:1.6rem;
  font-family:var(--sans)}
.endmatter h2{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--faint);font-weight:600;margin:0 0 1rem}
.srclist{list-style:none;margin:0 0 2.2rem;padding:0;font-size:.8rem}
.srclist li{margin:.55rem 0}
.srclist .doc{font-weight:600}
.srclist .filemeta{display:block;color:var(--muted);font-size:.7rem}
.notes{list-style:none;margin:0;padding:0;font-size:.78rem}
.note{display:flex;gap:1rem;padding:.9rem 0;border-top:1px solid var(--hairline);
  cursor:pointer}
.note:hover{background:var(--hover)}
.note:target{background:var(--hover)}
.note > div{flex:1;min-width:0}
.backref{flex:0 0 1.4rem;font-family:var(--mono);font-size:.72rem;
  color:var(--faint);text-decoration:none;text-align:right;padding-top:.15rem}
.backref:hover{color:var(--ink)}
/* the notes are a page, not a viewport: a long quote gets a fixed cap here,
   the one place in the artifact where nothing is resizable */
.note .quote{font-size:.84rem;max-height:15rem}
.colophon{margin-top:2.8rem;color:var(--muted);font-size:.72rem;
  line-height:1.55;display:flex;align-items:center;gap:.45rem}
.bd-mark{flex:0 0 auto}

/* ---- overlays ---- */
.overlay{position:fixed;inset:0;background:rgba(24,23,20,.85);z-index:90;
  display:none;align-items:center;justify-content:center;padding:1.5rem}
.overlay.open{display:flex}
.overlay > img{max-width:100%;max-height:100%;border-radius:2px;cursor:zoom-out;
  background:#fff}
.sheetbox{background:var(--paper);border-radius:4px;
  width:min(78rem,100%);height:auto;max-height:min(48rem,100%);
  display:flex;flex-direction:column;overflow:hidden}
.sheetbox header{display:flex;align-items:center;justify-content:space-between;
  font-family:var(--sans);font-size:.78rem;font-weight:600;
  padding:.7rem 1rem;border-bottom:1px solid var(--hairline)}
.sheetbox header .close{font-size:1.2rem}
.sheetscroll{overflow:auto;flex:1;background:var(--paper)}
.sheettable tbody th{min-width:2.6rem}
.sheettable td{max-width:18rem;cursor:cell}
.sheettable td.sel{box-shadow:inset 0 0 0 2px var(--ink)}
.sheettable td.cited.sel{box-shadow:inset 0 0 0 2px var(--ink)}
.namebox{font-family:var(--mono);font-size:.7rem;font-weight:500;color:var(--muted);
  margin-left:auto;margin-right:1rem;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;min-width:0}

/* ---- responsive / print ---- */
@media (max-width:1140px){
  .frame{display:block}
  .divider{display:none}
  .pagecol{max-width:44rem;margin:0 auto;padding:2.5rem 1.25rem 4rem}
  .railcol{background:none}
  .rail{position:static;max-height:none;padding:0}
  .resting{display:none}
  /* the phone card is not resizable, so there is no drag for the evidence to
     follow: it goes back to one column that scrolls whole, quote cap and all */
  .card{position:fixed;left:50%;transform:translateX(-50%);bottom:1rem;z-index:80;
    width:min(30rem,calc(100vw - 2rem));max-height:72vh;overflow:auto;resize:none;
    display:block}
  .card .quote{max-height:15rem}
  @keyframes rise{from{opacity:0;transform:translate(-50%,.5rem)}
    to{opacity:1;transform:translate(-50%,0)}}
  .overlay{padding:.6rem}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{
  .railcol,.divider,.overlay{display:none}
  .frame{display:block}
  .pagecol{max-width:none;padding:0}
  .note{break-inside:avoid}
  .claim{text-decoration:none}
}
:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
"""

SCRIPT = """
(function () {
  var rail = document.querySelector('.rail');
  var resting = document.querySelector('.resting');
  var sheetsEl = document.getElementById('bd-sheets');
  var sheets = sheetsEl ? JSON.parse(sheetsEl.textContent || '{}') : {};
  var active = null, activeCard = null;

  /* Python's f-string formatting rounds half to even on the double's exact
     value. Neither JS built-in matches: toFixed rounds ties toward +inf, and
     Intl's halfEven rounds a decimal re-parse (2.345 formats as 2.34 where
     Python says 2.35). So the mirror rounds exactly: mantissa and exponent
     out of the bits, scaled by 10^d under BigInt, half-even at the boundary. */
  function fixed(v, d, grouped) {
    var neg = v < 0 || Object.is(v, -0);
    var dv = new DataView(new ArrayBuffer(8));
    dv.setFloat64(0, Math.abs(v));
    var bits = dv.getBigUint64(0);
    var be = Number(bits >> 52n) & 0x7ff;
    var m = bits & 0xfffffffffffffn;
    var e = be === 0 ? -1074 : be - 1075;
    if (be !== 0) m |= 0x10000000000000n;
    var num = m * 10n ** BigInt(d), den = 1n;
    if (e >= 0) num <<= BigInt(e); else den = 1n << BigInt(-e);
    var q = num / den, twice = (num % den) * 2n;
    if (twice > den || (twice === den && (q & 1n) === 1n)) q += 1n;
    var s = q.toString().padStart(d + 1, '0');
    var whole = d ? s.slice(0, -d) : s;
    if (grouped) whole = whole.replace(/\\B(?=(\\d{3})+$)/g, ',');
    return (neg ? '-' : '') + whole + (d ? '.' + s.slice(-d) : '');
  }
  function fmt(raw) {
    if (raw === '' || raw == null) return '';
    var v = Number(raw);
    if (isNaN(v)) return raw;
    /* v === 0 ? 0 : v — the integer branch mirrors Python's int(), which
       drops the sign of negative zero; the decimal branches keep it */
    if (v === Math.trunc(v) && Math.abs(v) < 1e15) return fixed(v === 0 ? 0 : v, 0, true);
    if (Math.abs(v) < 1) return fixed(v, 4, false);
    return fixed(v, 0, true);
  }
  /* the workbook's own number format, mirrored from the Python renderer
     (fmt_cell); tests/test_fmt_parity.py holds the two together */
  function fmtCell(raw, format) {
    if (raw === '' || raw == null) return '';
    var v = Number(raw);
    if (!format || isNaN(v)) return fmt(raw);
    if (format.indexOf('%') >= 0) {
      var pm = format.match(/0\\.(0+)%/);
      return fixed(v * 100, pm ? pm[1].length : 0, false) + '%';
    }
    var dm = format.match(/0\\.(0+)/);
    var decimals = dm ? dm[1].length : 0;
    var grouped = format.indexOf(',') >= 0;
    var text = fixed(v, decimals, grouped);
    var qm = format.match(/"([^"]*)"/);
    var symbol = qm ? qm[1] : (format.indexOf('$') >= 0 ? '$' : '');
    return symbol + text;
  }
  function cellStyle(meta, ref, cited) {
    if (!meta || !meta.cells) return null;
    var idx = meta.cells[ref];
    if (idx == null) return null;
    return (meta.palette || [])[idx] || null;
  }
  function styleAttr(style, cited) {
    if (!style) return '';
    var rules = [];
    if (style.b) rules.push('font-weight:600');
    if (!cited) {
      if (style.bg) rules.push('background:#' + style.bg);
      if (style.fg) rules.push('color:#' + style.fg);
    }
    return rules.length ? ' style="' + rules.join(';') + '"' : '';
  }
  function colName(n) {
    var s = '';
    while (n > 0) { var r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = (n - 1 - r) / 26; }
    return s;
  }

  function deactivate() {
    if (activeCard) activeCard.hidden = true;
    if (active) active.classList.remove('active');
    if (resting) resting.style.display = '';
    active = activeCard = null;
  }
  function activate(n, claim) {
    var card = document.getElementById('card-' + n);
    if (!card) return;
    deactivate();
    if (resting) resting.style.display = 'none';
    card.querySelectorAll('img[data-ev]').forEach(function (img) {
      if (!img.src) {
        var stored = document.getElementById(img.dataset.ev);
        if (stored) img.src = stored.src;
      }
    });
    card.hidden = false;
    if (claim) {
      claim.classList.add('active');
      active = claim;
    }
    activeCard = card;
    if (window.matchMedia('(min-width: 1141px)').matches) {
      rail.scrollTop = 0;
      if (claim) {
        var r = claim.getBoundingClientRect();
        if (r.top < 0 || r.bottom > innerHeight) claim.scrollIntoView({block: 'center'});
      }
    }
  }

  function openSheet(key, cited) {
    var data = sheets[key];
    if (!data) return;
    var box = document.getElementById('sheetoverlay');
    var scroll = box.querySelector('.sheetscroll');
    box.querySelector('.sheetname').textContent =
      data.name.replace(/-/g, ' ').replace(/\\b\\w/g, function (ch) { return ch.toUpperCase(); });
    var citedCol = cited ? cited.replace(/\\d+$/, '') : null;
    var citedRow = cited ? cited.replace(/^[A-Z]+/, '') : null;
    var meta = data.meta || {};
    var widths = meta.widths || {};
    var namebox = box.querySelector('.namebox');
    if (namebox) namebox.textContent = '';
    var h = '<table class="sheettable"><thead><tr><th></th>';
    for (var c = 1; c <= data.ncols; c++) {
      var cn = colName(c);
      var w = widths[cn]
        ? ' style="min-width:' + Math.max(40, Math.min(400, Math.round(widths[cn] * 8))) + 'px"'
        : '';
      h += '<th' + (cn === citedCol ? ' class="citedcol"' : '') + w + '>' + cn + '</th>';
    }
    h += '</tr></thead><tbody>';
    for (var r = 1; r <= data.nrows; r++) {
      h += '<tr' + (String(r) === citedRow ? ' class="citedrow"' : '') + '><th>' + r + '</th>';
      for (var c2 = 1; c2 <= data.ncols; c2++) {
        var raw = data.rows[r - 1][c2 - 1];
        var ref = colName(c2) + r;
        var cls = [];
        if (ref === cited) cls.push('cited');
        if (raw !== '' && raw != null && isFinite(Number(raw))) cls.push('num');
        var style = cellStyle(meta, ref);
        h += '<td' + (cls.length ? ' class="' + cls.join(' ') + '"' : '') +
             styleAttr(style, ref === cited) + ' data-ref="' + ref + '"' +
             ' title="' + String(raw).replace(/"/g, '&quot;') + '">' +
             fmtCell(raw, style && style.fmt) + '</td>';
      }
      h += '</tr>';
    }
    h += '</tbody></table>';
    scroll.innerHTML = h;
    box.classList.add('open');
    var hlCell = scroll.querySelector('td.cited');
    if (hlCell) {
      scroll.scrollTop = hlCell.offsetTop - scroll.clientHeight / 2;
      scroll.scrollLeft = hlCell.offsetLeft - scroll.clientWidth / 2;
    }
  }

  document.addEventListener('click', function (e) {
    var claim = e.target.closest('a.claim');
    if (claim) {
      e.preventDefault();
      if (active === claim) deactivate();
      else activate(claim.dataset.claim, claim);
      return;
    }
    if (e.target.closest('[data-close]')) {
      var over = e.target.closest('.overlay');
      if (over) { over.classList.remove('open'); return; }
      deactivate(); return;
    }
    var sel = e.target.closest('.srcsel button');
    if (sel) {
      var box = sel.closest('.card');
      box.querySelectorAll('.srcsel button').forEach(function (b) { b.classList.remove('on'); });
      box.querySelectorAll('.cite').forEach(function (ct) { ct.classList.remove('on'); });
      sel.classList.add('on');
      box.querySelector('.cite[data-cite="' + sel.dataset.cite + '"]').classList.add('on');
      return;
    }
    var tab = e.target.closest('.tab');
    if (tab) {
      var evd = tab.closest('.evidence');
      evd.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('on'); });
      evd.querySelectorAll('.pane').forEach(function (p) { p.classList.remove('on'); });
      tab.classList.add('on');
      evd.querySelector('.pane[data-pane="' + tab.dataset.pane + '"]').classList.add('on');
      return;
    }
    var noteRow = e.target.closest('.note');
    if (noteRow && !e.target.closest('a') && !e.target.closest('summary')) {
      var noteN = noteRow.id.replace('note-', '');
      var noteClaim = document.getElementById('claim-' + noteN);
      if (noteClaim) {
        noteClaim.scrollIntoView({block: 'center'});
        activate(noteN, noteClaim);
      }
      return;
    }
    var sheetCell = e.target.closest('.sheettable td[data-ref]');
    if (sheetCell) {
      var sheetScroll = sheetCell.closest('.sheetscroll');
      var prevSel = sheetScroll.querySelector('td.sel');
      if (prevSel) prevSel.classList.remove('sel');
      sheetCell.classList.add('sel');
      var nb = document.querySelector('#sheetoverlay .namebox');
      if (nb) {
        var shown = sheetCell.textContent || '';
        var rawVal = sheetCell.getAttribute('title') || '';
        nb.textContent = sheetCell.dataset.ref + (shown ? ' \\u00B7 ' + shown : '') +
          (rawVal && rawVal !== shown ? ' (' + rawVal + ')' : '');
      }
      return;
    }
    var grid = e.target.closest('.grid[data-sheet]');
    if (grid) { openSheet(grid.dataset.sheet, grid.dataset.cited); return; }
    var img = e.target.closest('.plate img');
    if (img && img.src) {
      var zoom = document.getElementById('zoom');
      zoom.querySelector('img').src = img.src;
      zoom.classList.add('open');
      return;
    }
    var overlay = e.target.closest('.overlay');
    if (overlay && (e.target === overlay || overlay.id === 'zoom')) {
      overlay.classList.remove('open');
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelector('.overlay.open');
    if (open) open.classList.remove('open');
    else deactivate();
  });

  /* draggable divider */
  var divider = document.querySelector('.divider');
  if (divider) {
    var startX = 0, startW = 0;
    divider.addEventListener('pointerdown', function (e) {
      startX = e.clientX;
      startW = document.querySelector('.railcol').getBoundingClientRect().width;
      divider.classList.add('dragging');
      divider.setPointerCapture(e.pointerId);
    });
    divider.addEventListener('pointermove', function (e) {
      if (!divider.classList.contains('dragging')) return;
      var w = Math.min(Math.max(startW - (e.clientX - startX), 320), innerWidth - 420);
      document.documentElement.style.setProperty('--rail-w', w + 'px');
    });
    ['pointerup', 'pointercancel'].forEach(function (ev) {
      divider.addEventListener(ev, function () { divider.classList.remove('dragging'); });
    });
  }
})();
"""

STYLESHEET_MIN = _minify(STYLESHEET)
"""What the artifact ships: `STYLESHEET` minus comments and indentation."""

SCRIPT_MIN = _minify(SCRIPT)
"""What the artifact ships: `SCRIPT` minus comments and indentation."""
