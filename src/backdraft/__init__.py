"""Backdraft — drop-in provenance for factual claims.

One click from any claim to the evidence behind it: `ingest` anchors source
documents, `read`/`search` gate them into a model's context while minting
citation tokens, `bind` resolves those tokens back to their receipts, `render`
produces a self-contained artifact.
"""

from __future__ import annotations

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    """`__version__`, read from the installed distribution on first access.

    Derived rather than written down: a release bumps `pyproject.toml` and
    `.claude-plugin/plugin.json`, and the literal that used to live here was
    silently left at 0.1.0 from 0.2.0 through 0.5.0. A version that can drift is
    worse than one that cannot; `tests/test_version.py` pins all three together.

    Lazy (PEP 562) because `importlib.metadata` costs ~30ms to import and scan
    for a value on no code path — the same reason `extract/base` imports an
    extractor's module only when asked for it. The result is cached into the
    module's globals, so this runs at most once and normal attribute lookup
    answers afterwards.
    """
    if name != "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib.metadata  # noqa: PLC0415 - keep importing the package free

    try:
        version = importlib.metadata.version("backdraft")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - bare checkout
        # No installed distribution, so there is no version to be right about.
        version = "0+unknown"
    globals()["__version__"] = version
    return version
