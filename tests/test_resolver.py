"""Resolver tests: the sample repo end to end, then one test per resolution rule."""

from pathlib import Path

import pytest

from app.parser import ModuleInfo, ParsedRepo, RawImport, parse_repo
from app.resolver import Edge, relative_base, resolve_import, resolve_repo

SAMPLE = Path(__file__).parent / "fixtures" / "sample_repo"


def mod(name, is_package=False, imports=()):
    return ModuleInfo(name=name, path=name.replace(".", "/") + ".py",
                      is_package=is_package, loc=0, imports=list(imports))


# --- the sample repo, end to end ---------------------------------------------

@pytest.fixture(scope="module")
def edges():
    return resolve_repo(parse_repo(SAMPLE))


def test_sample_repo_internal_edges(edges):
    # Exactly the table in tests/fixtures/sample_repo/README.md
    runtime = {(e.source, e.target) for e in edges if e.kind == "internal" and not e.type_only}
    type_only = {(e.source, e.target) for e in edges if e.kind == "internal" and e.type_only}
    assert type_only == {("shop.models", "shop.orders")}
    assert runtime == {
        ("shop", "shop.models"),
        ("shop.models", "shop.utils"),
        ("shop.orders", "shop.payments"),
        ("shop.orders", "shop.models"),
        ("shop.payments", "shop.orders"),
        ("shop.payments", "shop.utils"),
        ("shop.api.routes", "shop.utils"),
        ("shop.api.routes", "shop.orders"),
        ("shop.api.routes", "shop.models"),
        ("tests.test_orders", "shop.orders"),
    }


def test_sample_repo_external_edges(edges):
    assert {(e.source, e.target, e.kind) for e in edges if e.kind != "internal"} == {
        ("shop.models", "json", "stdlib"),
        ("shop.models", "typing", "stdlib"),
        ("shop.utils", "os", "stdlib"),          # `import os.path` -> top-level `os`
        ("shop.utils", "re", "stdlib"),
        ("shop.api.routes", "requests", "third_party"),
        ("setup", "setuptools", "third_party"),
        ("tests.test_orders", "pytest", "third_party"),
    }


# --- one rule at a time ------------------------------------------------------

INTERNAL = {"a", "a.b", "a.b.c", "x", "x.y", "x.y.z", "pkg", "pkg.sub"}


@pytest.mark.parametrize("imp, expected", [
    (RawImport("a.b.c"), {("a.b.c", "internal")}),
    (RawImport("a.b.nope"), {("a.b", "internal")}),                    # longest internal prefix
    (RawImport("x.y", ("z",)), {("x.y.z", "internal")}),               # z is a submodule
    (RawImport("x.y", ("SomeClass",)), {("x.y", "internal")}),         # z is just a name
    (RawImport("x", ("y", "helper")), {("x.y", "internal"), ("x", "internal")}),
    (RawImport("x.y", ("*",)), {("x.y", "internal")}),
    (RawImport("os.path"), {("os", "stdlib")}),                        # externals by top-level name
    (RawImport("distutils.core", ("setup",)), {("distutils", "stdlib")}),  # removed in 3.12
    (RawImport("numpy.linalg"), {("numpy", "third_party")}),
    (RawImport("__future__", ("annotations",)), set()),
])
def test_absolute_imports(imp, expected):
    assert resolve_import(imp, mod("main"), INTERNAL) == expected


@pytest.mark.parametrize("importer, imp, expected", [
    (mod("pkg", is_package=True), RawImport("", ("sub",), 1), "pkg"),  # in __init__, "." = itself
    (mod("pkg.sub"), RawImport("", ("x",), 1), "pkg"),                  # in a module, "." = parent
    (mod("a.b.c"), RawImport("", ("x",), 2), "a"),
    (mod("a.b.c"), RawImport("y.z", ("x",), 2), "a.y.z"),
    (mod("a.b.c"), RawImport("", ("x",), 3), None),                     # climbs above `a`
    (mod("setup"), RawImport("", ("x",), 1), None),                     # top-level file has no package
])
def test_relative_base(importer, imp, expected):
    assert relative_base(imp, importer) == expected


def test_relative_import_of_a_submodule():
    imp = RawImport("", ("sub",), level=1)                     # from . import sub
    assert resolve_import(imp, mod("pkg", is_package=True), INTERNAL) == {("pkg.sub", "internal")}


def test_unresolvable_relative_import_is_dropped_not_external():
    imp = RawImport("missing", ("x",), level=1)                # from .missing import x
    assert resolve_import(imp, mod("setup"), INTERNAL) == set()


def test_self_import_is_ignored():
    imp = RawImport("", ("helper",), level=1)                  # `helper` is just a name in pkg
    assert resolve_import(imp, mod("pkg", is_package=True), INTERNAL) == set()


def test_script_can_import_its_neighbour_by_bare_name():
    # tests/ has no __init__.py, so tests/test_api.py can `from conftest import client`
    internal = INTERNAL | {"tests.conftest", "tests.test_api"}
    imp = RawImport("conftest", ("client",))
    assert resolve_import(imp, mod("tests.test_api"), internal) == {("tests.conftest", "internal")}


def test_bare_neighbour_import_does_not_work_inside_a_package():
    # pkg is a package: Python 3 has no implicit relative imports, so this is a library
    internal = INTERNAL | {"pkg.helpers"}
    assert resolve_import(RawImport("helpers"), mod("pkg.sub"), internal) == {("helpers", "third_party")}


def test_edge_is_type_only_only_if_every_import_is():
    a = mod("a", imports=[
        RawImport("b", type_only=True),
        RawImport("c", type_only=True),
        RawImport("c"),                 # one runtime import of c is enough
    ])
    parsed = ParsedRepo(modules={"a": a, "b": mod("b"), "c": mod("c")}, skipped={})
    assert {e.target: e.type_only for e in resolve_repo(parsed)} == {"b": True, "c": False}


def test_repeated_imports_add_up_to_weight():
    a = mod("a", imports=[
        RawImport("a.b"),
        RawImport("a.b", ("thing",)),
        RawImport("a.b", ("x", "y")),   # one statement -> counts once
        RawImport("os"),
    ])
    parsed = ParsedRepo(modules={"a": a, "a.b": mod("a.b")}, skipped={})
    assert resolve_repo(parsed) == [
        Edge("a", "a.b", "internal", 3),
        Edge("a", "os", "stdlib", 1),
    ]
