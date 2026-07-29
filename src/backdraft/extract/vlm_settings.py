"""Provider resolution for the VLM extractor — importable on its own.

The client is always the `openai` SDK; a router is injected through `base_url`,
never through a second SDK. This module is stdlib-only so `client_settings` can
be imported (and tested) without the openai SDK; `vlm.py` re-exports
it next to the extractor that uses it.
"""

from __future__ import annotations

from ..credentials import setting
from .base import ExtractionError

__all__ = [
    "DEFAULT_CONCURRENCY",
    "DEFAULT_RETRIES",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_IMAGE_HEIGHT",
    "SNAPSHOT_QUALITY",
    "DEFAULT_MODEL",
    "OPENROUTER_BASE_URL",
    "client_settings",
    "concurrency",
    "is_retryable",
    "retries",
    "run_ordered",
    "snapshot_max_height",
    "snapshot_quality",
    "timeout_seconds",
    "with_retries",
]

DEFAULT_MODEL = "google/gemini-3.1-flash-lite-preview"
"""The default: Gemini 3.1 Flash Lite through OpenRouter, a fast, cheap reader
that handles glossy layouts well. Overridden with `--config model=...` or
`BACKDRAFT_VLM_MODEL`."""

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def client_settings(config: dict) -> tuple[str, str, str | None]:
    """Resolve `(model, api_key, base_url)` from backdraft-scoped settings only.

    The client is always the `openai` SDK; a router is injected through
    `base_url`, never through a second SDK. There is one default provider —
    OpenRouter running Gemini 3.1 Flash Lite — and one rule for credentials:
    **ambient provider variables are never read.** `OPENAI_API_KEY` and
    `OPENROUTER_API_KEY` exported for other tools do not exist as far as this
    function is concerned; presence of a generic key is not consent to send
    documents to its provider. See `backdraft.credentials`.

    * `api_key`: `--config api_key=` → `BACKDRAFT_VLM_API_KEY` (env or
      `.backdraft/env`). Required.
    * `base_url`: `--config base_url=` → `BACKDRAFT_VLM_BASE_URL` → OpenRouter.
    * `model`: `--config model=` → `BACKDRAFT_VLM_MODEL` → Gemini 3.1 Flash
      Lite. Direct OpenAI (or any OpenAI-compatible endpoint) is explicit:
      set the base_url and the model together.
    """
    api_key = setting("BACKDRAFT_VLM_API_KEY", config, config_key="api_key")
    if not api_key:
        raise ExtractionError(
            "the vlm extractor needs a backdraft-scoped API key: set "
            "BACKDRAFT_VLM_API_KEY (env or .backdraft/env), or pass "
            "--config api_key=... — ambient OPENAI_API_KEY/OPENROUTER_API_KEY "
            "are deliberately not read"
        )
    base_url = (
        setting("BACKDRAFT_VLM_BASE_URL", config, config_key="base_url")
        or OPENROUTER_BASE_URL
    )
    model = setting("BACKDRAFT_VLM_MODEL", config, config_key="model") or DEFAULT_MODEL
    return str(model), str(api_key), str(base_url)


DEFAULT_CONCURRENCY = 15
"""Concurrent page transcriptions, a production-tested value."""

DEFAULT_TIMEOUT_SECONDS = 120
"""Per-page request timeout, as tested in production."""

DEFAULT_RETRIES = 4
"""Attempts per page before the error propagates."""

MAX_IMAGE_HEIGHT = 1056
"""Rendered page images are downscaled to this height — token-cost control
(dpi buys legibility, height caps what a page costs). Overridden with
`BACKDRAFT_SNAPSHOT_MAX_HEIGHT` via `snapshot_max_height`."""

SNAPSHOT_QUALITY = 85
"""WebP quality for stored page snapshots, a production-tested setting. Lives
here rather than vlm.py so `snapshot-pages` can import it without pulling in
the openai client. Overridden with `BACKDRAFT_SNAPSHOT_QUALITY` via
`snapshot_quality`."""


def _int_setting(name: str, config: dict, config_key: str, default: int) -> int:
    raw = setting(name, config, config_key=config_key)
    try:
        return max(1, int(raw)) if raw else default
    except ValueError:
        return default


def concurrency(config: dict) -> int:
    """`--config concurrency=` → `BACKDRAFT_VLM_CONCURRENCY` → 15."""
    return _int_setting("BACKDRAFT_VLM_CONCURRENCY", config, "concurrency", DEFAULT_CONCURRENCY)


def timeout_seconds(config: dict) -> int:
    """`--config timeout=` → `BACKDRAFT_VLM_TIMEOUT` → 120."""
    return _int_setting("BACKDRAFT_VLM_TIMEOUT", config, "timeout", DEFAULT_TIMEOUT_SECONDS)


def retries(config: dict) -> int:
    """`--config retries=` → `BACKDRAFT_VLM_RETRIES` → 4."""
    return _int_setting("BACKDRAFT_VLM_RETRIES", config, "retries", DEFAULT_RETRIES)


def snapshot_quality(config: dict | None = None) -> int:
    """`--config snapshot_quality=` → `BACKDRAFT_SNAPSHOT_QUALITY` → 85.

    A size/fidelity budget knob for the artifact. Display only, like the
    snapshot itself: snippets, hashes and tokens are computed from extracted
    text and cell values, never from pixels, so turning this changes artifact
    weight and nothing else.
    """
    return _int_setting(
        "BACKDRAFT_SNAPSHOT_QUALITY", config or {}, "snapshot_quality", SNAPSHOT_QUALITY
    )


def snapshot_max_height(config: dict | None = None) -> int:
    """`--config snapshot_max_height=` → `BACKDRAFT_SNAPSHOT_MAX_HEIGHT` → 1056.

    Same budget-knob rule as `snapshot_quality`. In the vision paths the cap
    also bounds the image the model reads (that is what the default exists
    for); citation identity still never derives from the pixels.
    """
    return _int_setting(
        "BACKDRAFT_SNAPSHOT_MAX_HEIGHT", config or {}, "snapshot_max_height", MAX_IMAGE_HEIGHT
    )


def run_ordered(items, fn, *, workers, progress=None):
    """Map `fn` over `items` concurrently, yielding results in input order.

    `progress(done, total)` is called after each completion, in completion
    order — the caller renders it however it likes. Exceptions propagate from
    the yield of the item that raised, so ordering of failures is deterministic
    too.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    items = list(items)
    total = len(items)
    done = 0
    lock = threading.Lock()

    def wrapped(item):
        nonlocal done
        try:
            return fn(item)
        finally:
            with lock:
                done += 1
                if progress is not None:
                    progress(done, total)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(wrapped, item) for item in items]
        for future in futures:
            yield future.result()


_TRANSIENT_MARKERS = (
    "rate limit",
    "too many requests",
    "overloaded",
    "overload",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "gateway",
    "upstream",
    "server disconnected",
)
"""Message fragments that mark a transient upstream failure, a
production-tested classification."""


def is_retryable(error: Exception) -> bool:
    """Whether a page transcription failure is worth another attempt.

    Retryable: timeouts, HTTP 429/502/503/504 (via a `status_code` attribute,
    the shape the openai SDK raises), transient upstream messages, and
    connection-level failures. Everything else — auth, bad request, content —
    fails fast; retrying those only spends money on the same answer.
    """
    if isinstance(error, TimeoutError):
        return True
    if getattr(error, "status_code", None) in {429, 502, 503, 504}:
        return True
    message = str(error).lower()
    if any(marker in message for marker in _TRANSIENT_MARKERS):
        return True
    return isinstance(error, (ConnectionError, OSError))


def with_retries(fn, *, attempts, base_delay=1.0, sleep=None, jitter=None):
    """Run `fn` with the production retry shape: classify, exponential backoff
    plus jitter, raise the last error once attempts are spent or on the first
    non-retryable one. `sleep`/`jitter` are injectable for tests."""
    import random
    import time

    sleep = sleep or time.sleep
    jitter = jitter or (lambda high: random.uniform(0, high))
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return fn()
        except Exception as error:  # noqa: BLE001 - classification decides
            if not is_retryable(error) or attempt >= attempts:
                raise
            sleep(base_delay * (2 ** (attempt - 1)) + jitter(base_delay))
