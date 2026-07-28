"""Records live in `.backdraft/records/`; the authored directory stays clean."""

from __future__ import annotations

import pathlib

from typer.testing import CliRunner

from backdraft.bind.binder import bind
from backdraft.cli import app
from backdraft.kernel.artifact import record_path, sidecar_path
from backdraft.render.sidecar import find_sidecar


def test_record_path_mirrors_the_relative_path() -> None:
    root = pathlib.Path("/proj")
    doc = pathlib.Path("/proj/deals/darnell/memo.md")
    assert record_path(root, doc) == pathlib.Path(
        "/proj/.backdraft/records/deals/darnell/memo.backdraft.json"
    )


def test_a_document_outside_the_root_falls_back_beside_itself() -> None:
    doc = pathlib.Path("/elsewhere/memo.md")
    assert record_path(pathlib.Path("/proj"), doc) == sidecar_path(doc)


def test_rooted_bind_writes_the_record_out_of_sight(registry, root, note) -> None:
    registry.ingest(note)
    doc = root / "memo.md"
    doc.write_text("No claims here.\n", encoding="utf-8")
    bind(doc, registry)
    assert not sidecar_path(doc).exists()
    expected = record_path(root.resolve(), doc.resolve())
    assert expected.is_file()
    assert find_sidecar(doc) == expected


def test_clean_moves_strays_and_removes_bound(registry, root, note) -> None:
    registry.ingest(note)
    doc = root / "memo.md"
    doc.write_text("No claims here.\n", encoding="utf-8")
    sidecar_path(doc).write_text("{}", encoding="utf-8")
    (root / "memo.bound.md").write_text("old projection", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["clean", str(root)])
    assert result.exit_code == 0, result.output
    assert not sidecar_path(doc).exists()
    assert not (root / "memo.bound.md").exists()
    assert record_path(root.resolve(), doc.resolve()).is_file()
