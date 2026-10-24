"""Post the gate's Markdown as one comment on the pull or merge request; later runs edit it."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MARKER = "<!-- llm-release-gate -->"
Send = Callable[..., Any]


class NoTarget(Exception):
    """Not a pull or merge request job, or the job has no token to comment with."""


@dataclass(frozen=True)
class Target:
    comments: str  # list with GET, create with POST
    edit: str  # one comment, `{id}` filled in
    edit_method: str
    headers: dict[str, str]
    run_url: str | None


def target(env: Mapping[str, str]) -> Target:
    """Where to comment, from the CI job's environment: GitHub Actions or GitLab CI."""
    if env.get("GITHUB_ACTIONS") == "true":
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
        if "pull_request" not in event:
            raise NoTarget("not a pull_request event")
        token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
        if not token:
            raise NoTarget(
                "set GITHUB_TOKEN: ${{ github.token }} in the job, with pull-requests: write"
            )
        api = env.get("GITHUB_API_URL", "https://api.github.com")
        issues = f"{api}/repos/{env['GITHUB_REPOSITORY']}/issues"
        run = env.get("GITHUB_RUN_ID")
        return Target(
            f"{issues}/{event['pull_request']['number']}/comments",
            f"{issues}/comments/{{id}}",
            "PATCH",
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{run}"
            if run
            else None,
        )
    if env.get("GITLAB_CI") == "true":
        if not env.get("CI_MERGE_REQUEST_IID"):
            raise NoTarget("not a merge request pipeline")
        token = env.get("GITLAB_TOKEN")
        if not token:
            raise NoTarget(
                "set GITLAB_TOKEN: a project access token with the api scope, as a masked CI/CD variable"
            )
        notes = (
            f"{env['CI_API_V4_URL']}/projects/{env['CI_PROJECT_ID']}"
            f"/merge_requests/{env['CI_MERGE_REQUEST_IID']}/notes"
        )
        return Target(
            notes,
            f"{notes}/{{id}}",
            "PUT",
            {"PRIVATE-TOKEN": token},
            env.get("CI_JOB_URL"),
        )
    raise NoTarget("not in a GitHub Actions or GitLab CI job")


def call(
    method: str, url: str, headers: dict[str, str], body: dict | None = None
) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url, data, {**headers, "Content-Type": "application/json"}, method=method
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def post(text: str, t: Target, send: Send | None = None) -> str:
    """Edit the gate's earlier comment or create one; return which."""
    send = send or call
    body = f"{MARKER}\n{text}" + (f"\n[Job log]({t.run_url})\n" if t.run_url else "")
    earlier = [
        c
        for c in send("GET", f"{t.comments}?per_page=100", t.headers)
        if MARKER in (c.get("body") or "")
    ]
    if earlier:
        send(
            t.edit_method, t.edit.format(id=earlier[0]["id"]), t.headers, {"body": body}
        )
        return "updated"
    send("POST", t.comments, t.headers, {"body": body})
    return "created"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("file", type=Path, help="Markdown from the gate's --markdown")
    p.add_argument(
        "--dry-run", action="store_true", help="print the comment, post nothing"
    )
    args = p.parse_args(argv)
    if not args.file.is_file():
        sys.exit(f"{args.file}: no such file")
    text = args.file.read_text()
    if args.dry_run:
        print(text, end="")
        return
    try:
        print(f"comment {post(text, target(os.environ))}")
    except NoTarget as e:
        sys.exit(f"cannot comment: {e}")
    except urllib.error.HTTPError as e:
        sys.exit(f"cannot comment: {e.code} {e.reason} from {e.url}")
    except urllib.error.URLError as e:
        sys.exit(f"cannot comment: {e.reason}")


if __name__ == "__main__":
    main()
