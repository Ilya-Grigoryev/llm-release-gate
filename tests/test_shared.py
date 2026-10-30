import io
import json
import threading
import urllib.error
import zipfile
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from llm_release_gate import shared

ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_TOKEN": "t",
    "GITHUB_API_URL": "https://api",
    "GITHUB_REPOSITORY": "me/app",
    "GITHUB_REPOSITORY_ID": "7",
}
LIST = "https://api/repos/me/app/actions/artifacts"


def artifact(id, days_ago=0, repo=7, expired=False):
    created = (
        (datetime.now(UTC) - timedelta(days=days_ago))
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {"id": id, "created_at": created, "expired": expired, "size_in_bytes": 10,
            "workflow_run": {"id": 100 + id, "head_repository_id": repo}}  # fmt: skip


def zipped(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return data.getvalue()


def test_the_newest_recent_artifact_of_this_repository_is_kept():
    found = [
        artifact(1, 1),
        artifact(2, 0, repo=8),
        artifact(3, 0, expired=True),
        artifact(4, 9),
        artifact(5, 2),
    ]
    zip_ = zipped(
        {"base.jsonl": '{"run": 1}\n', "base.native.jsonl": "{}\n", "x.log": ""}
    )
    answers = {
        f"{LIST}?name=llm-release-gate-runs-demo-v-s&per_page=20": json.dumps(
            {"artifacts": found}
        ).encode(),
        f"{LIST}/1/zip": zip_,
    }
    seen, kept = [], []

    def http(url, headers):
        seen.append((url, headers["Authorization"]))
        return answers[url]

    def keep(path):
        kept.append(
            (path.name, path.read_text(), path.with_name("base.native.jsonl").is_file())
        )

    line, note = shared.fetch("llm-release-gate-runs-demo-v-s", keep, 7, ENV, http)
    assert kept == [("base.jsonl", '{"run": 1}\n', True)]
    assert note is None and "run 101" in line
    assert all(auth == "Bearer t" for _, auth in seen)


def test_nothing_recent_or_no_github_runs_the_base():
    def http(url, headers):
        return json.dumps({"artifacts": [artifact(1, 9)]}).encode()

    assert "no recent" in shared.fetch("n", lambda p: None, 7, ENV, http)[0]
    assert shared.fetch("n", lambda p: None, 7, {}, http)[0].endswith(
        "not a GitHub Actions job"
    )
    assert (
        "no GITHUB_TOKEN"
        in shared.fetch("n", lambda p: None, 7, {"GITHUB_ACTIONS": "true"}, http)[0]
    )


def test_a_job_without_permission_gets_a_note_and_errors_never_raise():
    def forbidden(url, headers):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    line, note = shared.fetch("n", lambda p: None, 7, ENV, forbidden)
    assert "403" in line and "actions: read" in note

    def broken(url, headers):
        return (
            json.dumps({"artifacts": [artifact(1)]}).encode()
            if "name=" in url
            else b"not a zip"
        )

    line, note = shared.fetch("n", lambda p: None, 7, ENV, broken)
    assert "BadZipFile" in line and note is None


def test_a_redirect_to_storage_drops_the_token():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen[self.path] = self.headers.get("Authorization")
            if self.path == "/zip":
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{server.server_port}/blob"
                )
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"bytes")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        data = shared.get(
            f"http://127.0.0.1:{server.server_port}/zip", {"Authorization": "Bearer t"}
        )
    finally:
        server.shutdown()
    assert data == b"bytes" and seen == {"/zip": "Bearer t", "/blob": None}


def test_names_fit_a_pipeline_a_version_and_a_set():
    assert (
        shared.name("demo", "a" * 64, "b" * 64)
        == f"llm-release-gate-runs-demo-{'a' * 16}-{'b' * 16}"
    )


def test_only_this_repositorys_small_artifacts_and_safe_paths():
    big = {**artifact(1), "size_in_bytes": shared.MAX_BYTES + 1}
    zip_ = zipped({"x/../../evil.jsonl": "{}\n"})
    answers = {
        "list": json.dumps({"artifacts": [big, artifact(2)]}).encode(),
        "zip": zip_,
    }
    kept = []
    line, _ = shared.fetch(
        "n",
        lambda p: kept.append(p.name),
        7,
        ENV,
        lambda url, h: answers["zip" if url.endswith("/2/zip") else "list"],
    )
    assert kept == ["evil.jsonl"] and "run 102" in line
    assert (
        "GITHUB_REPOSITORY_ID"
        in shared.fetch("n", None, 7, {**ENV, "GITHUB_REPOSITORY_ID": ""}, None)[0]
    )


def test_a_vanished_artifact_or_an_odd_answer_is_no_permission_problem():
    def gone(url, headers):
        if "name=" in url:
            return json.dumps({"artifacts": [artifact(1)]}).encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    line, note = shared.fetch("n", lambda p: None, 7, ENV, gone)
    assert "404" in line and note is None
    line, note = shared.fetch("n", lambda p: None, 7, ENV, lambda url, h: b"[]")
    assert "AttributeError" in line and note is None
