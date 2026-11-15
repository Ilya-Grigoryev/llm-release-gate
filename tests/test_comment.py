import json
import urllib.error
from datetime import UTC, datetime

import pytest

from llm_release_gate import comment
from llm_release_gate.comment import MARKER, NoTarget, post, target


class FakeAPI:
    """Stands in for the GitHub or GitLab API: keeps comments, records every call."""

    def __init__(self, comments=()):
        self.comments = list(comments)
        self.calls = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        if method == "GET":
            return self.comments
        return {"id": 99}


def github_env(tmp_path, **extra):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7}}))
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": "me/gate",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_RUN_ID": "42",
        "GITHUB_TOKEN": "t0k",
        **extra,
    }


GITLAB_ENV = {
    "GITLAB_CI": "true",
    "CI_API_V4_URL": "https://git01lab.example/api/v4",
    "CI_PROJECT_ID": "123",
    "CI_MERGE_REQUEST_IID": "5",
    "CI_JOB_URL": "https://git01lab.example/me/gate/-/jobs/9",
    "GITLAB_TOKEN": "glpat",
}


def test_github_first_run_creates_the_comment(tmp_path):
    api = FakeAPI([{"id": 1, "body": "looks good"}])
    assert (
        post("**Release gate: ✅ pass**\n", target(github_env(tmp_path)), api)
        == "created"
    )
    (method0, url, headers, _), (method, create, _, body) = api.calls
    assert method0 == "GET"
    assert url == "https://api.github.com/repos/me/gate/issues/7/comments?per_page=100"
    assert headers["Authorization"] == "Bearer t0k"
    assert (method, create) == (
        "POST",
        "https://api.github.com/repos/me/gate/issues/7/comments",
    )
    assert body["body"].startswith(MARKER) and "✅ pass" in body["body"]
    assert "[Job log](https://github.com/me/gate/actions/runs/42)" in body["body"]


def test_a_later_run_edits_its_own_comment(tmp_path):
    api = FakeAPI(
        [{"id": 1, "body": "looks good"}, {"id": 3, "body": f"{MARKER}\nold verdict"}]
    )
    assert post("new verdict\n", target(github_env(tmp_path)), api) == "updated"
    method, url, _, body = api.calls[-1]
    assert (method, url) == (
        "PATCH",
        "https://api.github.com/repos/me/gate/issues/comments/3",
    )
    assert "new verdict" in body["body"] and len(api.calls) == 2


def test_gitlab_edits_its_note_on_the_merge_request():
    api = FakeAPI([{"id": 11, "body": f"{MARKER}\nold"}])
    assert post("new\n", target(GITLAB_ENV), api) == "updated"
    get, put = api.calls
    notes = "https://git01lab.example/api/v4/projects/123/merge_requests/5/notes"
    assert get[1] == f"{notes}?per_page=100&order_by=created_at&sort=asc"
    assert get[2] == {"PRIVATE-TOKEN": "glpat"}
    assert put[:2] == ("PUT", f"{notes}/11")
    assert "[Job log](https://git01lab.example/me/gate/-/jobs/9)" in put[3]["body"]


@pytest.mark.parametrize(
    "env, message",
    [
        ({}, "not in a GitHub Actions or GitLab CI job"),
        ({**GITLAB_ENV, "GITLAB_TOKEN": ""}, "set GITLAB_TOKEN"),
        ({**GITLAB_ENV, "CI_MERGE_REQUEST_IID": ""}, "not a merge request pipeline"),
    ],
)
def test_no_target_says_why(env, message):
    with pytest.raises(NoTarget, match=message):
        target(env)


def test_github_without_a_token_or_a_pull_request_says_why(tmp_path):
    with pytest.raises(NoTarget, match="set GITHUB_TOKEN"):
        target(github_env(tmp_path, GITHUB_TOKEN=""))
    push = tmp_path / "push.json"
    push.write_text(json.dumps({"ref": "refs/heads/dev"}))
    with pytest.raises(NoTarget, match="not a pull_request event"):
        target(github_env(tmp_path, GITHUB_EVENT_PATH=str(push)))


def test_the_cli_fails_with_a_message_without_a_token(tmp_path, monkeypatch):
    text = tmp_path / "comment.md"
    text.write_text("**Release gate: ✅ pass**\n")
    monkeypatch.setattr(comment.os, "environ", {**GITLAB_ENV, "GITLAB_TOKEN": ""})
    with pytest.raises(SystemExit, match="cannot comment: set GITLAB_TOKEN"):
        comment.main([str(text)])


def test_the_cli_reports_an_api_error(tmp_path, monkeypatch):
    text = tmp_path / "comment.md"
    text.write_text("verdict\n")
    monkeypatch.setattr(comment.os, "environ", GITLAB_ENV)

    def forbidden(method, url, headers, body=None):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(comment, "call", forbidden)
    with pytest.raises(SystemExit, match="cannot comment: 403 Forbidden"):
        comment.main([str(text)])


def test_a_dry_run_prints_the_comment_and_posts_nothing(tmp_path, monkeypatch, capsys):
    text = tmp_path / "comment.md"
    text.write_text("**Release gate: ❌ quality fail**\n")
    monkeypatch.setattr(comment, "call", lambda *a, **k: pytest.fail("posted"))
    comment.main([str(text), "--dry-run"])
    assert capsys.readouterr().out == "**Release gate: ❌ quality fail**\n"


def test_check_fails_before_any_paid_run_without_a_token(monkeypatch, capsys):
    monkeypatch.setattr(comment.os, "environ", {**GITLAB_ENV, "GITLAB_TOKEN": ""})
    with pytest.raises(SystemExit, match="cannot comment: set GITLAB_TOKEN"):
        comment.main(["--check"])
    monkeypatch.setattr(comment.os, "environ", GITLAB_ENV)
    comment.main(["--check"])
    assert capsys.readouterr().out == "can comment\n"


def test_without_a_verdict_the_request_still_hears_why(tmp_path, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(comment.os, "environ", GITLAB_ENV)
    monkeypatch.setattr(comment, "call", api)
    comment.main([str(tmp_path / "missing.md")])
    method, _, _, body = api.calls[-1]
    assert method == "POST" and "infra error" in body["body"]


def test_named_pipelines_keep_a_comment_each(tmp_path):
    api = FakeAPI(
        [
            {"id": 1, "body": f"{MARKER}\nunnamed verdict"},
            {"id": 2, "body": "<!-- llm-release-gate:sroie -->\nsroie verdict"},
        ]
    )
    t = target(github_env(tmp_path))
    assert (
        post("**Release gate: ✅ pass**\n", t, api, name="support-agent") == "created"
    )
    assert post("**Release gate: ✅ pass**\n", t, api, name="sroie") == "updated"
    created, edited = (c for c in api.calls if c[0] != "GET")
    assert created[3]["body"].startswith(
        "<!-- llm-release-gate:support-agent -->\n`support-agent` · **Release gate"
    )
    assert edited[1].endswith("/comments/2")


NOW = datetime(2026, 11, 15, 14, 5, tzinfo=UTC)


def project_with_cases(tmp_path, n):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "gate.yaml").write_text(
        "pipelines:\n  demo:\n    config: demo.yaml\n    golden: golden\n"
    )
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "inputs").mkdir()  # not a case
    for i in range(n):
        (tmp_path / "golden" / f"case-{i}.yaml").write_text("id: x\n")
    return tmp_path


def test_the_running_note_says_when_and_on_how_many_cases(tmp_path):
    note = comment.running(project_with_cases(tmp_path, 3), "demo", NOW)
    assert note.startswith("**Release gate: ⏳ running**\n")
    assert "Started 2026-11-15 14:05 UTC" in note and "on 3 cases." in note
    assert "on 1 case." in comment.running(
        project_with_cases(tmp_path / "one", 1), None, NOW
    )


def test_the_running_note_does_without_a_readable_gate_yaml(tmp_path):
    (tmp_path / "gate.yaml").write_text("pipelines: [broken")
    for directory, name in ((tmp_path, "demo"), (tmp_path / "missing", "demo")):
        note = comment.running(directory, name, NOW)
        assert "with this request's. The verdict replaces this note" in note
    assert " case" not in comment.running(
        project_with_cases(tmp_path / "p", 2), "other", NOW
    )


class Thread(FakeAPI):
    """Keeps what is posted, so a later run finds and edits it."""

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        if method == "GET":
            return list(self.comments)
        if method == "POST":
            self.comments.append({"id": len(self.comments) + 1, **body})
        else:
            cid = int(url.rsplit("/", 1)[1])
            next(c for c in self.comments if c["id"] == cid).update(body)
        return {"id": len(self.comments)}


def test_the_verdict_replaces_the_running_note(tmp_path, monkeypatch, capsys):
    api = Thread([{"id": 1, "body": "looks good"}])
    monkeypatch.setattr(comment.os, "environ", github_env(tmp_path))
    monkeypatch.setattr(comment, "call", api)
    project = project_with_cases(tmp_path / "p", 2)
    comment.main(["--running", "--project", str(project), "--name", "demo"])
    verdict = tmp_path / "comment.md"
    verdict.write_text("**Release gate: ✅ pass**\n")
    comment.main([str(verdict), "--name", "demo"])
    assert capsys.readouterr().out == "comment created\ncomment updated\n"
    assert len(api.comments) == 2
    body = api.comments[1]["body"]
    assert "✅ pass" in body and "running" not in body
    assert body.startswith("<!-- llm-release-gate:demo -->\n`demo` · ")


def test_the_running_note_fails_before_any_paid_run_without_a_token(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(comment.os, "environ", {**GITLAB_ENV, "GITLAB_TOKEN": ""})
    monkeypatch.setattr(comment, "call", lambda *a, **k: pytest.fail("posted"))
    with pytest.raises(SystemExit, match="cannot comment: set GITLAB_TOKEN"):
        comment.main(["--running", "--project", str(tmp_path)])


def test_dry_run_prints_the_running_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(comment, "call", lambda *a, **k: pytest.fail("posted"))
    comment.main(
        [
            "--running",
            "--dry-run",
            "--project",
            str(project_with_cases(tmp_path, 2)),
            "--name",
            "demo",
        ]
    )
    assert capsys.readouterr().out.startswith("**Release gate: ⏳ running**")
