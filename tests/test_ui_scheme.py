import pytest

pytest.importorskip("PyQt6.QtWebEngineCore")

from tars.ui.__main__ import resolve_asset  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    base = tmp_path / "tars"
    (base / "avatar" / "app").mkdir(parents=True)
    (base / "avatar" / "app" / "index.html").write_text("<html>")
    (base / "avatar" / "models" / "m").mkdir(parents=True)
    (base / "avatar" / "models" / "m" / "m.model3.json").write_text("{}")
    (base / "avatar" / "live2d").mkdir()
    (base / "avatar" / "live2d" / "m").symlink_to(base / "avatar" / "models" / "m")
    (tmp_path / "secret.txt").write_text("nope")
    roots = {"app": base / "avatar" / "app", "avatar": base / "avatar"}
    return base, roots


def test_serves_files_inside_roots(tree):
    base, roots = tree
    assert resolve_asset("app", "/index.html", roots, base).name == "index.html"
    assert (
        resolve_asset("avatar", "/live2d/m/m.model3.json", roots, base) is not None
    )  # via symlink


@pytest.mark.parametrize(
    "host,path",
    [("app", "/../../../secret.txt"), ("avatar", "/../../secret.txt"), ("evil", "/index.html"),
     ("app", "/missing.js"), ("avatar", "/app")],
)  # fmt: skip
def test_refuses_traversal_unknown_hosts_and_dirs(tree, host, path):
    base, roots = tree
    assert resolve_asset(host, path, roots, base) is None
