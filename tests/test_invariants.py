"""Kernel purity, enforced by reading the kernel's own source.

`kernel` imports nothing from the package and nothing outside the standard
library, and it performs no I/O. Everything above it — registry, extract, gate,
bind, render — depends on that being true, so it is a test, not a convention.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import subprocess
import sys
import types

import pytest

import backdraft.kernel

KERNEL = pathlib.Path(backdraft.kernel.__file__).parent
MODULES = sorted(KERNEL.glob("*.py"))

# Stdlib modules that would make the kernel impure even though they are stdlib:
# state, clocks, randomness, or the outside world.
#
# `pathlib` is deliberately absent: `artifact.py` computes artifact file names
# from a document's path, which is pure string math over an inert value. What
# would make it impure is *using* a path, so the filesystem methods are forbidden
# below instead of the import.
FORBIDDEN_STDLIB = {
    "argparse",
    "asyncio",
    "datetime",
    "io",
    "logging",
    "os",
    "random",
    "secrets",
    "shutil",
    "socket",
    "sqlite3",
    "subprocess",
    "tempfile",
    "threading",
    "time",
    "urllib",
    "uuid",
}

FORBIDDEN_CALLS = {"open", "print", "input", "exec", "eval", "compile"}

# Methods that reach the filesystem, whatever they are called on. `Path` brings
# these along; the kernel may hold a path but may never look through it.
FORBIDDEN_METHODS = {
    "exists",
    "glob",
    "is_dir",
    "is_file",
    "iterdir",
    "mkdir",
    "open",
    "read_bytes",
    "read_text",
    "rename",
    "rglob",
    "rmdir",
    "stat",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_the_kernel_has_the_modules_the_spec_names() -> None:
    assert {path.name for path in MODULES} == {
        "__init__.py",
        "model.py",
        "tokens.py",
        "hashing.py",
        "chunking.py",
        "claims.py",
        "errors.py",
        "artifact.py",
    }


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_absolute_imports_are_stdlib_only(path: pathlib.Path) -> None:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots = [(node.module or "").split(".")[0]]
        else:
            continue
        for root in roots:
            assert root != "backdraft", f"{path.name} imports the package absolutely"
            assert root in sys.stdlib_module_names, f"{path.name} imports {root!r}"
            assert root not in FORBIDDEN_STDLIB, f"{path.name} imports {root!r}"


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_relative_imports_stay_inside_the_kernel(path: pathlib.Path) -> None:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.level:
            assert node.level == 1, f"{path.name} reaches outside the kernel"
            assert (KERNEL / f"{(node.module or '').split('.')[0]}.py").exists(), (
                f"{path.name} imports an unknown kernel module: {node.module!r}"
            )


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_no_io_calls(path: pathlib.Path) -> None:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, f"{path.name} calls {node.func.id}()"


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_no_filesystem_methods(path: pathlib.Path) -> None:
    """Holding a `Path` is fine; looking through one is not."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in FORBIDDEN_METHODS, (
                f"{path.name} calls .{node.func.attr}()"
            )


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_every_module_documents_its_contract(path: pathlib.Path) -> None:
    assert ast.get_docstring(_tree(path)), f"{path.name} has no module docstring"


def test_importing_the_kernel_loads_nothing_above_it() -> None:
    """A fresh interpreter importing the kernel pulls in no other subpackage."""
    program = (
        "import sys, backdraft.kernel;"
        "print('\\n'.join(n for n in sys.modules if n.startswith('backdraft.')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )
    loaded = result.stdout.split()
    assert loaded, "expected backdraft.kernel to be loaded"
    assert all(name.startswith("backdraft.kernel") for name in loaded), loaded


def test_the_kernel_package_has_no_re_export_surface() -> None:
    """Module paths are the kernel's API — `kernel/__init__.py` is a docstring.

    A flat surface would have to alias `parse` three ways and would let a caller
    write `from backdraft.kernel import normalize`, hiding which module owns it.
    """
    assert not hasattr(backdraft.kernel, "__all__")
    exported = [
        name
        for name, value in vars(backdraft.kernel).items()
        if not name.startswith("__") and not isinstance(value, types.ModuleType)
    ]
    assert exported == [], exported


@pytest.mark.parametrize(
    "path", [p for p in MODULES if p.name != "__init__.py"], ids=lambda path: path.name
)
def test_every_submodule_exports_what_it_promises(path: pathlib.Path) -> None:
    """Each kernel submodule's `__all__` is its contract: every name must exist."""
    module = importlib.import_module(f"backdraft.kernel.{path.stem}")
    declared = getattr(module, "__all__", None)
    assert declared, f"{path.name} declares no __all__"
    for name in declared:
        assert hasattr(module, name), f"{path.name}.__all__ names a missing {name!r}"
