"""Runs other jobs of this repository left as GitHub artifacts, one per version and test set (D-007).

A job uploads each arm it paid for as `llm-release-gate-runs-PIPELINE-VERSION-SET` (16 characters of each hash). A
later job that needs a version's runs asks GitHub for that name: whatever ran it, a request's base, a request's
candidate (after merge it is the target branch's version) or a refresh, nothing runs twice within the age limit.
"""

import io
import json
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

PREFIX = "llm-release-gate-runs-"
MAX_BYTES = 200 * 1024 * 1024
Get = Callable[[str, dict[str, str]], bytes]


def name(pipeline: str, version_hash: str, set_hash: str) -> str:
    return f"{PREFIX}{pipeline}-{version_hash[:16]}-{set_hash[:16]}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(url: str, headers: dict[str, str]) -> bytes:
    """GET URL; a redirect is followed without HEADERS, so the token never reaches the storage it points to."""
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"):
            raise
        with urllib.request.urlopen(e.headers["Location"], timeout=300) as r:
            return r.read()


def fetch(
    artifact: str,
    keep: Callable[[Path], None],
    days: float,
    env: Mapping[str, str],
    http: Get = get,
) -> tuple[str, str | None]:
    """Hand the runs of the newest artifact ARTIFACT from this repository's own jobs, at most DAYS old, to KEEP.

    Returns a line for the log and, when the job lacks the permission to read artifacts, a note for the comment.
    Never raises: without earlier runs the base simply runs."""
    if env.get("GITHUB_ACTIONS") != "true":
        return "earlier runs: not a GitHub Actions job", None
    token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
    if not token:
        return "earlier runs: no GITHUB_TOKEN", None
    api = env.get("GITHUB_API_URL", "https://api.github.com")
    repo = f"{api}/repos/{env['GITHUB_REPOSITORY']}/actions/artifacts"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    since = datetime.now(UTC) - timedelta(days=days)
    try:
        listing = json.loads(
            http(f"{repo}?name={urllib.parse.quote(artifact)}&per_page=20", headers)
        )
        found = sorted(
            (
                a
                for a in listing.get("artifacts", [])
                if not a.get("expired")
                and a.get("size_in_bytes", 0) <= MAX_BYTES
                and datetime.fromisoformat(a["created_at"]) >= since
                # a fork's workflow may upload under any name
                and str((a.get("workflow_run") or {}).get("head_repository_id"))
                == env.get("GITHUB_REPOSITORY_ID")
            ),
            key=lambda a: a["created_at"],
            reverse=True,
        )
        if not found:
            return f"earlier runs: no recent {artifact}", None
        newest = found[0]
        data = http(f"{repo}/{newest['id']}/zip", headers)
        with TemporaryDirectory() as tmp, zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.namelist():
                if member.endswith(".jsonl"):  # base.jsonl and its .native.jsonl
                    (Path(tmp) / Path(member).name).write_bytes(z.read(member))
            for runs in Path(tmp).glob("*.jsonl"):
                if not runs.name.endswith(".native.jsonl"):
                    keep(runs)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return (
                f"earlier runs: GitHub answered {e.code}",
                (
                    "Base ran again: this job cannot read earlier runs. Give it `actions: read` in the workflow's "
                    "`permissions`."
                ),
            )
        return f"earlier runs: GitHub answered {e.code}", None
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as e:  # fmt: skip
        return f"earlier runs: {type(e).__name__}: {e}", None
    return f"earlier runs: {artifact} from run {newest['workflow_run'].get('id')}", None
