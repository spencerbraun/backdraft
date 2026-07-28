"""The kernel: pure, stdlib-only, imports nothing else from the package.

Grammar, hashing, chunking, claim parsing, the artifact format and the vocabulary
of types. No I/O, no SQLite, no configuration. Everything above this layer —
registry, extract, gate, bind, render — imports the kernel; the kernel imports
none of them. `tests/test_invariants.py` enforces that by reading this source.

**The module paths are the API.** There is deliberately no flat re-export surface
here: callers write `from backdraft.kernel.tokens import parse`, not
`from backdraft.kernel import parse_token`. Two reasons. The module a name lives
in is information — `hashing.normalize` and a bare `normalize` are not equally
readable — and a flat surface has to invent disambiguating aliases (`parse`, in
three different modules, became `parse_token` / `parse_locator` /
`parse_citation`) that name nothing actually defined anywhere. Each submodule's
own `__all__` is its contract; this package has none.
"""

