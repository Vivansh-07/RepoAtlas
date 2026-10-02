"""Parser tests. Most use tests/fixtures/sample_repo, whose README lists what it contains."""

import os
from pathlib import Path, PurePosixPath

import pytest

from app import config
from app.errors import NoPythonFiles, RepoTooLarge
from app.parser import (
    RawImport, count_loc, detect_source_roots, find_python_files, parse_repo, path_to_module,
)

SAMPLE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture(scope="module")
def parsed():
    return parse_repo(SAMPLE)


# --- path -> module name ---------------------------------------------------

@pytest.mark.parametrize("path, expected", [
    ("flask/app.py", ("flask.app", False)),
    ("flask/__init__.py", ("flask", True)),
    ("flask/json/provider.py", ("flask.json.provider", False)),
    ("setup.py", ("setup", False)),
    ("__init__.py", None),            # repo root itself isn't a package
    ("my-tool/run.py", None),         # '-' can't appear in an import
    ("class/models.py", None),        # keyword
    ("v1.2/models.py", None),         # '.' inside a folder name
    ("2fa/check.py", None),           # can't start with a digit
])
def test_path_to_module(path, expected):
    assert path_to_module(PurePosixPath(path)) == expected


def test_src_without_init_is_a_source_root():
    assert detect_source_roots(SAMPLE) == [SAMPLE / "src", SAMPLE]


def test_src_with_init_is_a_normal_package(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "utils.py").write_text("x = 1\n")
    assert detect_source_roots(tmp_path) == [tmp_path]
    assert set(parse_repo(tmp_path).modules) == {"src", "src.utils"}


def test_nested_projects_get_their_own_root(tmp_path):
    # Shaped like Flask: examples/tutorial is its own project with package `flaskr`,
    # and both it and the main repo have tests/conftest.py.
    for rel in ["tests/conftest.py",
                "examples/tutorial/pyproject.toml",
                "examples/tutorial/flaskr/__init__.py",
                "examples/tutorial/flaskr/db.py",
                "examples/tutorial/tests/conftest.py"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")

    modules = parse_repo(tmp_path).modules
    assert {name: m.path for name, m in modules.items()} == {
        "tests.conftest": "tests/conftest.py",                  # main project wins the short name
        "flaskr": "examples/tutorial/flaskr/__init__.py",       # named the way its own code imports it
        "flaskr.db": "examples/tutorial/flaskr/db.py",
        "examples.tutorial.tests.conftest": "examples/tutorial/tests/conftest.py",  # clash -> full path
    }


# --- file discovery ---------------------------------------------------------

def test_discovery_skips_build_and_hidden_dirs():
    rel = {p.relative_to(SAMPLE).as_posix() for p in find_python_files(SAMPLE)}
    assert "build/generated.py" not in rel
    assert ".github/release.py" not in rel
    assert "src/shop/models.py" in rel


def test_too_many_files_raises(monkeypatch):
    monkeypatch.setattr(config, "MAX_PY_FILES", 3)
    with pytest.raises(RepoTooLarge):
        find_python_files(SAMPLE)


def test_empty_repo_raises(tmp_path):
    (tmp_path / "README.md").write_text("no python here")
    with pytest.raises(NoPythonFiles):
        parse_repo(tmp_path)


def test_symlinks_are_ignored(tmp_path):
    (tmp_path / "real.py").write_text("import os\n")
    try:
        os.symlink(tmp_path / "real.py", tmp_path / "link.py")
    except OSError:
        pytest.skip("creating symlinks needs extra permissions on this OS")
    assert [p.name for p in find_python_files(tmp_path)] == ["real.py"]


# --- the whole sample repo --------------------------------------------------

def test_module_names(parsed):
    assert set(parsed.modules) == {
        "setup", "broken", "tests.test_orders",
        "shop", "shop.models", "shop.utils", "shop.orders", "shop.payments",
        "shop.api", "shop.api.routes",
    }


def test_paths_are_repo_relative_with_forward_slashes(parsed):
    assert parsed.modules["shop.models"].path == "src/shop/models.py"
    assert parsed.modules["shop.api"].path == "src/shop/api/__init__.py"


def test_packages_are_flagged(parsed):
    assert parsed.modules["shop"].is_package
    assert parsed.modules["shop.api"].is_package
    assert not parsed.modules["shop.orders"].is_package


def test_unimportable_path_is_skipped_with_reason(parsed):
    assert "scripts/my-tool/run.py" in parsed.skipped


def test_broken_file_is_kept_with_error(parsed):
    broken = parsed.modules["broken"]
    assert broken.parse_error == "SyntaxError at line 4"
    assert broken.imports == []


# --- import extraction ------------------------------------------------------

def test_absolute_imports(parsed):
    assert parsed.modules["shop.utils"].imports == [RawImport("os.path"), RawImport("re")]


def test_relative_imports_keep_their_level(parsed):
    assert set(parsed.modules["shop.orders"].imports) == {
        RawImport("", ("payments",), level=1),       # from . import payments
        RawImport("models", ("Product",), level=1),  # from .models import Product
    }


def test_two_dot_and_star_imports(parsed):
    imports = set(parsed.modules["shop.api.routes"].imports)
    assert RawImport("orders", ("Order",), level=2) in imports
    assert RawImport("models", ("*",), level=2) in imports


def test_function_level_import_is_found(parsed):
    assert RawImport("shop", ("utils",)) in parsed.modules["shop.payments"].imports


def test_large_file_is_kept_but_not_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_BYTES", 10)
    (tmp_path / "big.py").write_text("import os\n" * 5)
    big = parse_repo(tmp_path).modules["big"]
    assert big.imports == [] and "not parsed" in big.parse_error


def test_count_loc_ignores_blanks_and_comments():
    assert count_loc(b"# header\n\nimport os\n    # indented comment\nx = 1  # trailing\n") == 2
