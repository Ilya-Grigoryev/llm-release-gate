"""The programs in Get started, in each language, answer through the gate against a fake OpenAI server."""

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from llm_release_gate.command import Command
from llm_release_gate.pipeline import Case, Fatal, Retryable, load_config

PAGE = (
    Path(__file__).parent.parent / "dashboard" / "app" / "docs" / "start" / "page.mdx"
)
INVOICE = "NORTHWIND SUPPLIES LTD\nTOTAL DUE 1,249.50\n"
PROMPT = "Read the invoice below. Answer in JSON with the keys vendor, date and total."
FIELDS = {"vendor": "Northwind Supplies Ltd", "date": "14.03.2026", "total": "1249.50"}


def tabs() -> dict[str, dict[str, str]]:
    """Language → {file: text}, as the page shows them: each block names its file in its first line."""
    found = {}
    for label, body in re.findall(
        r'<Tab label="(.+?)">(.*?)</Tab>', PAGE.read_text(), re.DOTALL
    ):
        blocks = re.findall(r"```\w+\n(.*?)```", body, re.DOTALL)
        found[label] = {re.match(r"(?:#|//) (\S+?):", b)[1]: b for b in blocks}
    return found


TABS = tabs()
RUNTIME = {"Python": "python", "Node.js": "node", "Go": "go"}

REPLIES = {
    "ok": (200, None),
    "notjson": (200, None),
    "quota": (
        429,
        {
            "message": "You exceeded your current quota",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        },
    ),
    "credits": (
        429,
        {
            "message": "You have no credits remaining",
            "type": "insufficient_quota",
            "code": "credit_balance_exhausted",
        },
    ),
    "rate": (
        429,
        {
            "message": "Rate limit reached",
            "type": "requests",
            "code": "rate_limit_exceeded",
        },
    ),
    "auth": (
        401,
        {
            "message": "Incorrect API key",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        },
    ),
    "down": (
        500,
        {"message": "The server had an error", "type": "server_error", "code": None},
    ),
    "bad": (
        400,
        {
            "message": "Unsupported parameter",
            "type": "invalid_request_error",
            "code": "unsupported_parameter",
        },
    ),
}


class Provider(BaseHTTPRequestHandler):
    """Answers chat completions as `server.mode` says and keeps each request."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append((self.path, self.headers["Authorization"], body))
        status, error = REPLIES[self.server.mode]
        content = (
            json.dumps(FIELDS)
            if self.server.mode == "ok"
            else "Sorry, I cannot read it."
        )
        reply = (
            {"error": error}
            if error
            else {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4.1-mini-2025-04-14",
                "system_fingerprint": "fp_1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                },
            }
        )
        data = json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def provider():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


@pytest.fixture(params=list(RUNTIME))
def project(request, tmp_path, monkeypatch, provider):
    """A project with the page's config and program for one language, the gate running from its root."""
    language = request.param
    if shutil.which(RUNTIME[language]) is None:
        if os.environ.get("GITHUB_ACTIONS"):  # its job installs every runtime (ci.yml)
            pytest.fail(f"needs {RUNTIME[language]} to check the {language} example")
        pytest.skip(f"needs {RUNTIME[language]}")
    files = {
        **TABS[language],
        "prompts/extract.md": PROMPT,
        "inputs/inv-001.txt": INVOICE,
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    if (
        "gate.yaml" in files
    ):  # the page's lines for gate.yaml: `prepare`, as `pr` runs it
        subprocess.run(yaml.safe_load(files["gate.yaml"])["prepare"], check=True)
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{provider.server_port}/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider.seen.clear()
    case = Case(
        id="inv-001", inputs={"text": tmp_path / "inputs" / "inv-001.txt"}, expected={}
    )
    return Command(load_config(Path("configs/invoice.yaml"))), case


def test_prepare_passes_in_a_tree_without_the_program(tmp_path):
    """`pr` prepares the target branch's tree too; on the first request it has no program yet."""
    for files in TABS.values():
        if "gate.yaml" in files:
            prepare = yaml.safe_load(files["gate.yaml"])["prepare"]
            subprocess.run(prepare, cwd=tmp_path, check=True)


def test_every_language_has_its_tab():
    assert list(TABS) == list(RUNTIME)


def test_the_program_answers_with_what_the_provider_said(project, provider):
    command, case = project
    provider.mode = "ok"
    a = command.run(case)
    assert a.output == FIELDS and json.loads(a.raw) == FIELDS
    assert (a.input_tokens, a.output_tokens, a.model) == (
        120,
        30,
        "gpt-4.1-mini-2025-04-14",
    )
    assert (a.fingerprint, a.finish_reason, a.request_id) == (
        "fp_1",
        "stop",
        "chatcmpl-1",
    )
    [(path, key, sent)] = provider.seen
    assert path == "/v1/chat/completions" and key == "Bearer sk-test"
    assert sent["model"] == "gpt-4.1-mini-2025-04-14" and sent["temperature"] == 0
    assert sent["response_format"] == {"type": "json_object"}
    assert [m["content"] for m in sent["messages"]] == [PROMPT, INVOICE]


def test_an_answer_that_is_not_json_is_no_answer(project, provider):
    command, case = project
    provider.mode = "notjson"
    a = command.run(case)
    assert a.output is None and a.raw == "Sorry, I cannot read it."


@pytest.mark.parametrize(
    "mode, error",
    [
        ("quota", Fatal),
        ("credits", Fatal),
        ("auth", Fatal),
        ("rate", Retryable),
        ("down", Retryable),
        ("bad", RuntimeError),
    ],
)
def test_the_exit_code_tells_the_gate_to_stop_retry_or_fail_the_run(
    project, provider, mode, error
):
    command, case = project
    provider.mode = mode
    with pytest.raises(error):
        command.run(case)
