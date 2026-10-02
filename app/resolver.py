"""Turn each raw import into a dependency edge: either to a module inside the repo,
or to an external library (standard library or third-party).
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Container
from dataclasses import dataclass
from typing import Literal

from app.parser import ModuleInfo, ParsedRepo, RawImport

Kind = Literal["internal", "stdlib", "third_party"]

# sys.stdlib_module_names only lists the *running* Python's modules. These were
# removed in 3.12/3.13 or renamed after Python 2, but older repos still import them.
# (_typeshed exists only for type checkers, inside `if TYPE_CHECKING:` blocks.)
_EXTRA_STDLIB = frozenset({
    "aifc", "asynchat", "asyncore", "audioop", "cgi", "cgitb", "chunk", "crypt",
    "distutils", "imghdr", "imp", "lib2to3", "mailcap", "msilib", "nis", "nntplib",
    "ossaudiodev", "pipes", "smtpd", "sndhdr", "spwd", "sunau", "telnetlib", "uu", "xdrlib",
    "__builtin__", "BaseHTTPServer", "CGIHTTPServer", "ConfigParser", "Cookie",
    "HTMLParser", "Queue", "SimpleHTTPServer", "SocketServer", "StringIO", "Tkinter",
    "cPickle", "cStringIO", "commands", "cookielib", "copy_reg", "htmlentitydefs",
    "httplib", "robotparser", "thread", "urllib2", "urlparse", "xmlrpclib",
    "_typeshed",
})
STDLIB = frozenset(sys.stdlib_module_names) | _EXTRA_STDLIB


@dataclass(frozen=True)
class Edge:
    source: str     # the importing module
    target: str     # a repo module, or an external top-level name ("os", "requests")
    kind: Kind
    weight: int     # number of import statements in `source` that lead to `target`


def longest_internal_prefix(name: str, internal: Container[str]) -> str | None:
    """'a.b.c' -> 'a.b.c' if that's a repo module, else 'a.b', else 'a', else None."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in internal:
            return candidate
    return None


def relative_base(imp: RawImport, importer: ModuleInfo) -> str | None:
    """The absolute name a relative import points at.

    In shop/api/routes.py, `from ..orders import Order` -> 'shop.orders'.
    Returns None if the dots climb above the top-level package (Python itself
    would raise ImportError there).
    """
    # One dot means "the package I'm in": the package itself for an __init__.py,
    # the parent for a plain module.
    package = importer.name if importer.is_package else importer.name.rpartition(".")[0]
    parts = package.split(".") if package else []
    if imp.level > len(parts):
        return None
    parts = parts[: len(parts) - (imp.level - 1)]   # every extra dot goes one level up
    if imp.module:
        parts += imp.module.split(".")
    return ".".join(parts)


def script_folder(importer: ModuleInfo, internal: Container[str]) -> str | None:
    """The importer's folder, if that folder is not a package.

    Python puts a script's own folder on sys.path (pytest does the same for test
    files), so code there can import its neighbours by bare name: tests/test_api.py
    can `import conftest` to get tests/conftest.py. Inside a package that doesn't
    work in Python 3, so we return None there.
    """
    if importer.is_package:
        return None
    folder = importer.name.rpartition(".")[0]
    return folder if folder and folder not in internal else None


def resolve_import(
    imp: RawImport, importer: ModuleInfo, internal: Container[str]
) -> set[tuple[str, Kind]]:
    """Where one import statement points, as (target, kind) pairs.

    A set, so `from x import a, b` counts once towards the x edge, not twice.
    """
    if imp.module == "__future__":       # a compiler switch, not a dependency
        return set()
    if imp.level:
        base = relative_base(imp, importer)
    else:
        base = imp.module
        folder = script_folder(importer, internal)
        if folder:
            # A neighbour file wins, like it would on sys.path. The startswith
            # check stops a match on some shorter prefix outside the folder.
            found = longest_internal_prefix(f"{folder}.{base}", internal)
            if found and found.startswith(folder + "."):
                base = f"{folder}.{base}"
    if not base:
        return set()

    # `from base import name` can pull in a submodule (`from shop import utils`)
    # or just something defined inside base (`from shop.models import Product`).
    candidates = {base}
    if imp.names:
        candidates = {f"{base}.{n}" if f"{base}.{n}" in internal else base for n in imp.names}

    targets: set[tuple[str, Kind]] = set()
    for candidate in candidates:
        found = longest_internal_prefix(candidate, internal)
        if found:
            if found != importer.name:   # ignore self-imports
                targets.add((found, "internal"))
        elif not imp.level:
            # Relative imports always mean "inside this repo", so one we can't
            # find is dropped instead of being labelled a third-party library.
            top = candidate.partition(".")[0]
            targets.add((top, "stdlib" if top in STDLIB else "third_party"))
    return targets


def resolve_repo(parsed: ParsedRepo) -> list[Edge]:
    """Every dependency edge in the repo, duplicates merged into `weight`."""
    internal = parsed.modules.keys()
    counts: Counter[tuple[str, str, Kind]] = Counter()
    for module in parsed.modules.values():
        for imp in module.imports:
            for target, kind in resolve_import(imp, module, internal):
                counts[(module.name, target, kind)] += 1
    return [Edge(src, dst, kind, weight) for (src, dst, kind), weight in sorted(counts.items())]


if __name__ == "__main__":
    # Day 1 check: print a repo's internal import edges.
    #   python -m app.resolver tests/fixtures/sample_repo
    #   python -m app.resolver https://github.com/pallets/click
    from app.cloner import open_repo
    from app.parser import parse_repo

    with open_repo(sys.argv[1]) as repo_path:
        parsed = parse_repo(repo_path)
    edges = resolve_repo(parsed)

    internal_edges = [e for e in edges if e.kind == "internal"]
    print(f"{len(parsed.modules)} modules, {len(internal_edges)} internal edges "
          f"(A -> B means A imports B)\n")
    for e in internal_edges:
        print(f"  {e.source} -> {e.target}" + (f"   x{e.weight}" if e.weight > 1 else ""))
    for kind in ("stdlib", "third_party"):
        names = sorted({e.target for e in edges if e.kind == kind})
        print(f"\n{kind} ({len(names)}): {', '.join(names)}")
