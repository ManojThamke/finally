import pytest


@pytest.fixture
def static(tmp_path):
    root = tmp_path / "static"
    (root / "_next").mkdir(parents=True)
    (root / "index.html").write_text("INDEX")
    (root / "about.html").write_text("ABOUT")
    (root / "docs").mkdir()
    (root / "docs" / "index.html").write_text("DOCS")
    (root / "_next" / "app.js").write_text("JS")
    return root


def test_static_serving(client, static):
    assert client.get("/").text == "INDEX"
    assert client.get("/about").text == "ABOUT"
    assert client.get("/docs/").text == "DOCS"
    assert client.get("/_next/app.js").text == "JS"
    assert client.get("/some/client/route").text == "INDEX"  # SPA fallback


def test_missing_asset_and_api_404(client, static):
    assert client.get("/_next/missing.js").status_code == 404
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_no_traversal(client, static, tmp_path):
    (tmp_path / "secret.txt").write_text("SECRET")
    assert "SECRET" not in client.get("/..%2fsecret.txt").text


def test_api_works_without_frontend(client):
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200
