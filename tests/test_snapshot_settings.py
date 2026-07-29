"""Snapshot budget knobs: backdraft-scoped, display only, never identity.

`BACKDRAFT_SNAPSHOT_QUALITY` and `BACKDRAFT_SNAPSHOT_MAX_HEIGHT` follow the
same settings mechanism as `BACKDRAFT_VLM_*` (config → env → `.backdraft/env`)
and default to the production values. The second half pins the constraint that
makes them safe to turn: citation tokens are computed from extracted text and
cell values, never from pixels, so two ingests differing only in their page
snapshots mint identical anchors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backdraft.extract.base import ExtractedPage, PageImage, register
from backdraft.extract.vlm_settings import snapshot_max_height, snapshot_quality
from backdraft.registry.store import Registry


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for name in ("BACKDRAFT_SNAPSHOT_QUALITY", "BACKDRAFT_SNAPSHOT_MAX_HEIGHT", "BACKDRAFT_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # out of reach of any real .backdraft/env


# ---- resolution -------------------------------------------------------------


def test_defaults_are_the_production_values() -> None:
    assert snapshot_quality() == 85
    assert snapshot_max_height() == 1056


def test_env_overrides_the_default(monkeypatch) -> None:
    monkeypatch.setenv("BACKDRAFT_SNAPSHOT_QUALITY", "60")
    monkeypatch.setenv("BACKDRAFT_SNAPSHOT_MAX_HEIGHT", "720")
    assert snapshot_quality() == 60
    assert snapshot_max_height() == 720


def test_config_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("BACKDRAFT_SNAPSHOT_QUALITY", "60")
    assert snapshot_quality({"snapshot_quality": "40"}) == 40
    assert snapshot_max_height({"snapshot_max_height": "500"}) == 500


def test_env_file_is_read(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".backdraft").mkdir()
    (tmp_path / ".backdraft" / "env").write_text(
        "BACKDRAFT_SNAPSHOT_QUALITY=70\n", encoding="utf-8"
    )
    assert snapshot_quality() == 70


def test_garbage_falls_back_to_the_default(monkeypatch) -> None:
    monkeypatch.setenv("BACKDRAFT_SNAPSHOT_QUALITY", "lossless")
    assert snapshot_quality() == 85


# ---- snapshots are display, never identity ----------------------------------


class _Snapshotting:
    """One page of fixed text under whichever snapshot bytes the test picks."""

    name = "snapshot-budget-probe"
    version = "1"
    deterministic = True

    def __init__(self) -> None:
        self.image = PageImage(data=b"HIGH", format="webp", width=816, height=1056)

    def can_handle(self, path: Path, media_type: str) -> bool:
        return path.suffix == ".probe"

    def extract(self, path: Path, config: dict):
        yield ExtractedPage(
            number=1, kind="page",
            text="Net operating income was $1,429,600.\n\nOccupancy closed at 91.4%.",
            image=self.image,
        )


_EXTRACTOR = _Snapshotting()
register(_EXTRACTOR)


def _tokens(root: Path, image: PageImage) -> tuple[list[str], bytes]:
    root.mkdir()
    source = root / "doc.probe"
    source.write_text("irrelevant", encoding="utf-8")
    _EXTRACTOR.image = image
    registry = Registry.open(root)
    try:
        document = registry.ingest(source, extractor=_EXTRACTOR.name)
        anchors = registry.anchors_for_page(document.slug, 1)
        stored = registry.page_image(document.slug, 1)
        return sorted(anchor.token for anchor in anchors), stored.data
    finally:
        registry.close()


def test_changing_the_snapshot_never_changes_tokens(tmp_path) -> None:
    full = PageImage(data=b"FULL-QUALITY-BYTES", format="webp", width=816, height=1056)
    lean = PageImage(data=b"lean", format="webp", width=389, height=504)
    tokens_full, stored_full = _tokens(tmp_path / "full", full)
    tokens_lean, stored_lean = _tokens(tmp_path / "lean", lean)
    assert stored_full != stored_lean  # the snapshots really differ
    assert tokens_full == tokens_lean  # the citations do not
