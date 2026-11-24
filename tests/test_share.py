"""The share door: one motion study, watched by anyone signed in with GitHub who has the link. GitHub itself is faked:
nothing here goes out. What is tested is what the door opens (the study's assembly, played) and what it never does
(a source, a check, another Note, anything changed), and that no GitHub token is kept."""
import json
import urllib.parse

import httpx
import pytest
from starlette.testclient import TestClient

from monet import github
from monet.app import create_app

TOKEN = "gho_FAKE_TOKEN_never_kept_0123456789"


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    root = tmp_path_factory.mktemp("share")
    mp = pytest.MonkeyPatch()
    mp.setenv("MONET_GITHUB_ID", "Iv1.test")
    mp.setenv("MONET_GITHUB_SECRET", "secret-of-the-app")

    def fake(request: httpx.Request):
        if request.url.path == "/login/oauth/access_token":
            body = urllib.parse.parse_qs(request.content.decode())
            ok = body.get("code") == ["good"] and body.get("client_secret") == ["secret-of-the-app"]
            return httpx.Response(200, json={"access_token": TOKEN} if ok else {"error": "bad_verification_code"})
        if request.url.path == "/user":
            assert request.headers["authorization"] == f"Bearer {TOKEN}"
            return httpx.Response(200, json={"id": 4242, "login": "octo-viewer", "email": "never@kept.example"})
        return httpx.Response(404)
    real = httpx.Client
    mp.setattr(github.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(fake)))
    app = create_app(root / "storage", root / "data", max_users=4)
    with TestClient(app) as owner:
        assert owner.post("/api/login", json={"card": app.state.admin["card"], "password": "correct horse"}).status_code == 200
        assert owner.post("/w/admin/api/projects", json={"name": "arm", "template": "mg400_rakis"}).status_code == 200
        study = {"of": "rakis", "fps": 30, "length": 60, "tracks": {}}
        assert owner.put("/w/admin/api/p/arm/studies/tool%20lock", json={"study": study}).status_code == 200
        yield app, owner, root
    mp.undo()


def signed_in(app):
    """A browser that went through GitHub's sign-in (faked) and came back."""
    c = TestClient(app, follow_redirects=False)
    go = c.get("/auth/github", params={"next": "/s/whatever"})
    assert go.status_code == 302 and go.headers["location"].startswith(github.AUTHORIZE)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(go.headers["location"]).query)
    assert q["client_id"] == ["Iv1.test"] and "scope" not in q            # no scope: the public profile only
    back = c.get("/auth/github/back", params={"code": "good", "state": q["state"][0]})
    assert back.status_code == 302 and back.headers["location"] == "/s/whatever"
    assert github.COOKIE in c.cookies
    return c


def test_a_link_is_made_once_and_kept_only_as_its_hash(setup):
    app, owner, root = setup
    assert owner.get("/w/admin/api/p/arm/studies/tool%20lock/share").json()["shared"] is None
    made = owner.post("/w/admin/api/p/arm/studies/tool%20lock/share").json()
    token = made["link"].rsplit("/", 1)[1]
    assert made["github"] and len(token) >= 20
    kept = (root / "data" / "shares.json").read_text()
    sid = owner.get("/w/admin/api/p/arm").json()["studies"]["tool lock"]["id"]
    assert token not in kept and sid in kept
    assert owner.get("/w/admin/api/p/arm/studies/tool%20lock/share").json()["shared"]["made"]
    assert "link" not in owner.get("/w/admin/api/p/arm/studies/tool%20lock/share").json()
    assert owner.post("/w/admin/api/p/arm/studies/nope/share").status_code == 404
    # a new one closes the one before
    again = owner.post("/w/admin/api/p/arm/studies/tool%20lock/share").json()["link"].rsplit("/", 1)[1]
    viewer = signed_in(app)
    assert viewer.get(f"/s/{token}/api/state").status_code == 404
    assert viewer.get(f"/s/{again}/api/state").status_code == 200
    owner.delete("/w/admin/api/p/arm/studies/tool%20lock/share")
    assert viewer.get(f"/s/{again}/api/state").status_code == 404


def test_the_door_opens_the_study_and_nothing_else(setup):
    app, owner, root = setup
    token = owner.post("/w/admin/api/p/arm/studies/tool%20lock/share").json()["link"].rsplit("/", 1)[1]
    # watching needs no sign-in (Kaspar, 2026-11-24): GitHub is only for writing a note
    nobody = TestClient(app, follow_redirects=False)
    assert 'data-share="1"' in nobody.get(f"/s/{token}").text
    anon = nobody.get(f"/s/{token}/api/state").json()["share"]
    assert anon["viewer"] is None and anon["signin"] == f"/auth/github?next=/s/{token}"
    assert nobody.get(f"/s/{token}/api/p/arm/n/rakis").status_code == 200
    assert nobody.get(f"/s/{token}/api/p/arm/n/nest_back").status_code == 404
    viewer = signed_in(app)
    assert 'data-share="1"' in viewer.get(f"/s/{token}").text
    state = viewer.get(f"/s/{token}/api/state").json()
    assert state["share"] == {**state["share"], "project": "arm", "study": "tool lock", "note": "rakis", "viewer": "octo-viewer"}
    assert state["agent"] == "" and state["mine"] is False
    proj = viewer.get(f"/s/{token}/api/p/arm").json()
    assert [n["name"] for n in proj["notes"]] == ["rakis"] and list(proj["studies"]) == ["tool lock"]
    note = viewer.get(f"/s/{token}/api/p/arm/n/rakis").json()
    assert "source" not in note and note["checks"] == [] and "checks" not in note["report"] and "snaps" not in note["report"]
    assert viewer.get(f"/s/{token}/api/p/arm/rev").json()["rev"]
    # not another Note, project, or anything of the person's door
    for path in ("/api/p/arm/n/nest_back", "/api/p/other/n/rakis", "/api/p/arm/n/rakis/checks", "/api/p/arm/n/rakis/source", "/api/p/arm/brief",
                 "/api/p/arm/docs", "/api/p/arm/archive.zip", "/api/projects", "/api/manual", "/api/p/arm/n/rakis/export.stl", "/agent/status"):
        assert viewer.get(f"/s/{token}{path}").status_code in (404, 405), path
    for path in ("/api/p/arm/n/rakis/joints/z", "/api/p/arm/studies/tool%20lock", "/api/p/arm/n/rakis/source"):
        assert viewer.put(f"/s/{token}{path}", json={}).status_code in (404, 405), path
    # a GitHub cookie is no login of Monet's
    assert viewer.get("/w/admin/api/state").status_code == 401
    # no token of GitHub's anywhere
    for f in root.rglob("*"):
        if f.is_file():
            assert TOKEN.encode() not in f.read_bytes(), f
            assert b"never@kept.example" not in f.read_bytes(), f


def test_signing_in_is_refused_when_it_was_not_started_here(setup):
    app, _owner, root = setup
    c = TestClient(app, follow_redirects=False)
    go = c.get("/auth/github", params={"next": "https://evil.example/x"})
    state = urllib.parse.parse_qs(urllib.parse.urlparse(go.headers["location"]).query)["state"][0]
    stranger = TestClient(app, follow_redirects=False)      # the state, but not the browser that asked for it
    assert stranger.get("/auth/github/back", params={"code": "good", "state": state}).status_code == 400
    assert c.get("/auth/github/back", params={"code": "good", "state": state + "x"}).status_code == 400
    assert c.get("/auth/github/back", params={"code": "bad", "state": state}).status_code == 400
    back = c.get("/auth/github/back", params={"code": "good", "state": state})
    assert back.headers["location"] == "/"                    # never back to somewhere else
    # a cookie made up or changed is nobody
    who = json.loads(__import__("base64").urlsafe_b64decode(c.cookies[github.COOKIE].split(".")[0] + "=="))
    assert who["login"] == "octo-viewer" and set(who) == {"id", "login", "until"}
    from monet import auth
    from monet.store import Store
    secret, raw = auth.session_secret(Store(root / "data")), c.cookies[github.COOKIE]
    assert github.viewer(secret, {github.COOKIE: raw})["login"] == "octo-viewer"
    value, sig = raw.split(".")
    forged = __import__("base64").urlsafe_b64encode(json.dumps({**who, "login": "someone-else"}).encode()).decode().rstrip("=")
    assert github.viewer(secret, {github.COOKIE: f"{forged}.{sig}"}) is None
    assert github.viewer(secret, {github.COOKIE: f"{value}.{sig[:-2]}AA"}) is None


def test_the_repository_is_a_setting_of_the_project(setup):
    _app, owner, _ = setup
    assert owner.put("/w/admin/api/p/arm/repository", json={"repository": "https://github.com/kkallas/arm.git"}).json()["repository"] == "kkallas/arm"
    assert owner.get("/w/admin/api/p/arm").json()["repository"] == "kkallas/arm"
    assert owner.put("/w/admin/api/p/arm/repository", json={"repository": "not a repo"}).status_code == 400
    assert owner.put("/w/admin/api/p/arm/repository", json={"repository": "a/b c"}).status_code == 400


def test_a_renamed_study_keeps_its_link(setup):
    """The link holds the study by its id: renamed (as the canvas does it: written under the new name with its id,
    the old name removed), it still opens it, under its new name."""
    app, owner, _ = setup
    token = owner.post("/w/admin/api/p/arm/studies/tool%20lock/share").json()["link"].rsplit("/", 1)[1]
    study = owner.get("/w/admin/api/p/arm").json()["studies"]["tool lock"]
    assert owner.put("/w/admin/api/p/arm/studies/tool%20unlocks", json={"study": study}).status_code == 200
    assert owner.delete("/w/admin/api/p/arm/studies/tool%20lock").status_code == 200
    viewer = signed_in(app)
    assert viewer.get(f"/s/{token}/api/state").json()["share"]["study"] == "tool unlocks"
    assert list(viewer.get(f"/s/{token}/api/p/arm").json()["studies"]) == ["tool unlocks"]
    assert owner.get("/w/admin/api/p/arm/studies/tool%20unlocks/share").json()["shared"]
    # keyed again (the timeline sends no id): still the same study, still the same link
    owner.put("/w/admin/api/p/arm/studies/tool%20unlocks", json={"study": {"of": "rakis", "fps": 30, "length": 90, "tracks": {}}})
    assert owner.get("/w/admin/api/p/arm").json()["studies"]["tool unlocks"]["id"] == study["id"]
    assert viewer.get(f"/s/{token}/api/state").status_code == 200
    # removed: the link opens nothing
    owner.delete("/w/admin/api/p/arm/studies/tool%20unlocks")
    assert viewer.get(f"/s/{token}/api/state").status_code == 404
