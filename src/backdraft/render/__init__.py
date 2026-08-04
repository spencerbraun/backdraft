"""render — the artifact and its projections.

Three renderings of one bind run, from an authored document plus its sidecar and
nothing else (the registry is never opened here):

* `html` — the single-file artifact: the document, a receipt behind every claim,
  a visible Unresolved section, and a JSON island that teaches its own decoding.
* `footnotes` — the plain-markdown projection.
* `sidecar` — the machine-readable record alone, `backdraft/artifact-v1`.

`theme` sits beside them: it resolves the user's look into one CSS block `html`
emits after the stylesheet. Display only — no rendering *decision* depends on
it, and an unthemed render is byte-identical to one from before it existed.

Export style (shared by every package above the kernel): **names**, never
submodules. The three renderers each spell their entry point `render`, so they
are reached by module path — `from backdraft.render import html`, then
`html.render(...)` — which also means importing this package does not drag all
three in. `render.cli` is not imported here either: it needs typer; the library
does not.
"""

from __future__ import annotations

from .placement import Placement, locate
from .sidecar import FORMAT, LEGEND, SIDECAR_SUFFIX, sidecar_path

__all__ = [
    "Placement",
    "locate",
    "FORMAT",
    "LEGEND",
    "SIDECAR_SUFFIX",
    "sidecar_path",
]
