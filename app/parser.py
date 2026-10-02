"""Find a repo's Python files, name each one as a module, and pull out its imports.

Nothing here imports or runs the repo's code: `ast.parse` only reads it as a tree,
so a malicious repo can't execute anything on our server.
"""

from __future__ import annotations

import ast
import keyword
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app import config
from app.errors import NoPythonFiles, RepoTooLarge

log = logging.getLogger(__name__)

# A folder holding one of these is the root of a Python project. Big repos often
# nest several: examples, plugins, sub-libraries (e.g. Flask's examples/tutorial).
PROJECT_MARKERS = frozenset({"pyproject.toml", "setup.py", "setup.cfg"})


@dataclass(frozen=True)
class RawImport:
    """One import as written in the source, before we know where it points.

    import a.b            -> RawImport("a.b")
    from a.b import c, d  -> RawImport("a.b", ("c", "d"))
    from ..x import y     -> RawImport("x", ("y",), level=2)
    from . import y       -> RawImport("", ("y",), level=1)
    """
    module: str
    names: tuple[str, ...] = ()   # empty means a plain `import module`
    level: int = 0                # number of leading dots (0 = absolute import)


@dataclass
class ModuleInfo:
    name: str                     # dotted name, e.g. "flask.app"
    path: str                     # repo-relative, always with "/" (also on Windows)
    is_package: bool              # True for __init__.py; changes what "." means
    loc: int
    imports: list[RawImport] = field(default_factory=list)
    parse_error: str | None = None


@dataclass
class ParsedRepo:
    modules: dict[str, ModuleInfo]
    skipped: dict[str, str]       # path -> reason, for .py files that aren't modules


def _walk(repo_dir: Path) -> Iterator[tuple[Path, list[str]]]:
    """(folder, file names) for every folder outside SKIP_DIRS and hidden folders."""
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        # Assigning to dirnames[:] (in place) tells os.walk not to descend into
        # the removed folders; sorting makes the walk order deterministic.
        dirnames[:] = sorted(
            d for d in dirnames if d not in config.SKIP_DIRS and not d.startswith(".")
        )
        yield Path(dirpath), sorted(filenames)


def find_python_files(repo_dir: Path) -> list[Path]:
    found: list[Path] = []
    for folder, filenames in _walk(repo_dir):
        for filename in filenames:
            path = folder / filename
            # A symlink could point outside the repo (e.g. at a server file).
            if not filename.endswith(".py") or path.is_symlink():
                continue
            found.append(path)
            if len(found) > config.MAX_PY_FILES:
                raise RepoTooLarge(f"Repo has more than {config.MAX_PY_FILES} Python files")
    return found


def detect_source_roots(repo_dir: Path) -> list[Path]:
    """Folders that act like an entry on sys.path, deepest first.

    That's the repo root plus every nested project (a folder with a PROJECT_MARKERS
    file that isn't itself a package), and the `src/` folder of any of them.
    `src/` only counts when it has no __init__.py: some projects really do write
    `from src.utils import x`, and then `src` is part of the module name.
    """
    projects = [repo_dir] + [
        folder for folder, filenames in _walk(repo_dir)
        if folder != repo_dir
        and PROJECT_MARKERS.intersection(filenames)
        and "__init__.py" not in filenames
    ]
    roots: list[Path] = []
    for project in projects:
        roots.append(project)
        src = project / "src"
        if src.is_dir() and not (src / "__init__.py").exists():
            roots.append(src)
    return sorted(roots, key=lambda p: len(p.parts), reverse=True)


def path_to_module(rel_path: PurePosixPath) -> tuple[str, bool] | None:
    """'flask/app.py' -> ('flask.app', False); 'flask/__init__.py' -> ('flask', True).

    Returns None when no import statement could ever reach the file, e.g.
    'my-scripts/run.py' ('-' isn't allowed in a name) or a top-level __init__.py.
    """
    parts = list(rel_path.with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    if not parts or not all(p.isidentifier() and not keyword.iskeyword(p) for p in parts):
        return None
    return ".".join(parts), is_package


def extract_imports(tree: ast.AST) -> list[RawImport]:
    # ast.walk visits every node, so imports inside functions, `if` and
    # `try` blocks are included too. They're still real dependencies.
    imports: list[RawImport] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(RawImport(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = tuple(alias.name for alias in node.names)
            imports.append(RawImport(node.module or "", names, node.level))
    return imports


def count_loc(source: bytes) -> int:
    """Non-blank lines that aren't just a comment."""
    text = source.decode("utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def _parse_module(path: Path, rel: str, name: str, is_package: bool) -> ModuleInfo:
    info = ModuleInfo(name=name, path=rel, is_package=is_package, loc=0)
    if path.stat().st_size > config.MAX_FILE_BYTES:
        info.parse_error = f"over {config.MAX_FILE_BYTES:,} bytes, not parsed"
        return info
    source = path.read_bytes()
    info.loc = count_loc(source)
    try:
        # Passing bytes (not str) lets ast honour a `# -*- coding: ... -*-` line.
        info.imports = extract_imports(ast.parse(source, filename=rel))
    except (SyntaxError, ValueError, RecursionError) as exc:
        # e.g. Python 2 code, null bytes, absurdly deep nesting
        line = getattr(exc, "lineno", None)
        info.parse_error = type(exc).__name__ + (f" at line {line}" if line else "")
        log.warning("Could not parse %s: %s", rel, info.parse_error)
    return info


def parse_repo(repo_dir: Path) -> ParsedRepo:
    roots = detect_source_roots(repo_dir)
    modules: dict[str, ModuleInfo] = {}
    skipped: dict[str, str] = {}

    # Pair each file with its nearest (deepest) root, then handle files from
    # shallow roots first, so the main project claims names like "tests.conftest"
    # before a nested example project can.
    entries = [
        (next(r for r in roots if path.is_relative_to(r)), path)
        for path in find_python_files(repo_dir)
    ]
    entries.sort(key=lambda entry: (len(entry[0].parts), entry[1]))

    for root, path in entries:
        rel = path.relative_to(repo_dir).as_posix()
        mapped = path_to_module(PurePosixPath(path.relative_to(root).as_posix()))
        if mapped and mapped[0] in modules:
            # Two projects both define this name (e.g. tests/conftest.py): fall
            # back to the full path from the repo root, which is always unique.
            mapped = path_to_module(PurePosixPath(rel))
        if mapped is None:
            skipped[rel] = "path is not an importable module name"
            continue
        name, is_package = mapped
        if name in modules:
            skipped[rel] = f"same module name as {modules[name].path}"
            continue
        # Keep files that fail to parse: other modules may still import them, and
        # dropping them would make those imports look like third-party libraries.
        modules[name] = _parse_module(path, rel, name, is_package)

    if not modules:
        raise NoPythonFiles("No importable Python files found in this repository")
    return ParsedRepo(modules, skipped)


if __name__ == "__main__":
    # Manual check:
    #   python -m app.parser tests/fixtures/sample_repo
    #   python -m app.parser https://github.com/pallets/click
    import sys
    from contextlib import nullcontext

    from app.cloner import clone_repo, parse_repo_url

    target = sys.argv[1]
    source = clone_repo(parse_repo_url(target)) if target.startswith("https://") \
        else nullcontext(Path(target))
    with source as repo_path:
        parsed = parse_repo(repo_path)

    errors = [m for m in parsed.modules.values() if m.parse_error]
    print(f"{len(parsed.modules)} modules, {len(errors)} with parse errors, "
          f"{len(parsed.skipped)} files skipped\n")
    for m in sorted(parsed.modules.values(), key=lambda m: m.name):
        flag = f"  !! {m.parse_error}" if m.parse_error else ""
        print(f"{m.name:<40} {m.loc:>5} loc {len(m.imports):>4} imports  {m.path}{flag}")
    for rel, reason in parsed.skipped.items():
        print(f"skipped {rel}: {reason}")
