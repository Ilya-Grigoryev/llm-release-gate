"""The SROIE pipeline in a browser: pick a receipt, read it with a version under test, see the fields on the scan.

`uv run --env-file ../../.env python -m sroie_example.web`, then open http://127.0.0.1:8767. The page runs the versions
of `configs/` through the gate's own loader, compares the fields with the labels by the gate's `field_match` and prices
the calls with `prices.yaml`. Scans and labels are read from `../../data/SROIE2019/train`; nothing is copied.
"""

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import yaml
from openai import OpenAI, OpenAIError

from llm_release_gate.metrics import field_match, score
from llm_release_gate.pipeline import (
    Case,
    Fatal,
    Retryable,
    config_hash,
    load_config,
    load_pipeline,
)
from llm_release_gate.prices import load_prices, usd
from sroie_example.pipeline import FIELDS, SCORING, labels

HERE = Path(__file__).resolve().parents[2]
DATA = HERE.parents[1] / "data" / "SROIE2019" / "train"
PAGE = Path(__file__).with_name("web.html")
VERSIONS = {  # the page's names for the configs
    "text": ("One call, OCR text", "sroie-text.yaml"),
    "steps": ("Two calls, extract then check", "sroie-steps.yaml"),
    "image": ("One call, the scan", "sroie-image.yaml"),
}
ID = re.compile(r"[A-Za-z0-9]+")
MAX_TIMES = 5


class Recorder:
    """Stands between a pipeline and the OpenAI client and keeps every response, so each step can be shown."""

    def __init__(self, client):
        self.client, self.responses = client, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        r = self.client.chat.completions.create(**request)
        self.responses.append(r)
        return r


def ocr_lines(path: Path) -> list[dict]:
    """The OCR lines of a receipt: the four corners and the text."""
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(",", 8)
        if len(parts) == 9:
            try:
                out.append({"box": [int(x) for x in parts[:8]], "text": parts[8]})
            except ValueError:
                continue
        # lines without eight coordinates are not drawn
    return out


class Desk:
    def __init__(self, client, data: Path, prices: dict, ids: list[str]):
        self.client, self.data, self.prices, self.ids = client, data, prices, ids
        self.configs = {
            k: load_config(HERE / "configs" / f) for k, (_, f) in VERSIONS.items()
        }
        self.hashes = {k: config_hash(c)[:8] for k, c in self.configs.items()}

    def receipt(self, rid: str) -> Case:
        if not ID.fullmatch(rid) or not (self.data / "box" / f"{rid}.txt").is_file():
            raise KeyError(f"no receipt {rid} in {self.data.name}")
        box = self.data / "box" / f"{rid}.txt"
        return Case(id=rid, inputs={"text": box, "image": self.data / "img" / f"{rid}.jpg"},
                    expected=labels(self.data / "entities" / f"{rid}.txt"), scoring=SCORING)  # fmt: skip

    def listing(self) -> list[dict]:
        out = []
        for rid in self.ids:
            try:
                want = self.receipt(rid).expected
            except (KeyError, OSError, ValueError):
                continue
            out.append(
                {"id": rid, "company": want.get("company"), "total": want.get("total")}
            )
        return out

    def describe(self, rid: str) -> dict:
        case = self.receipt(rid)
        return {"id": rid, "labels": case.expected, "lines": ocr_lines(case.inputs["text"]),
                "scan": case.inputs["image"].is_file()}  # fmt: skip

    def read(self, rid: str, version: str) -> dict:
        """One run of a version on a receipt, as the gate's runner would score it, with each model call."""
        if version not in self.configs:
            raise ValueError(f"no version {version}")
        case, config = self.receipt(rid), self.configs[version]
        if config.input == "image" and not case.inputs["image"].is_file():
            raise ValueError(f"receipt {rid} has no scan")
        recorder = Recorder(self.client)
        try:
            answer = load_pipeline(config, client=recorder).run(case)
        except (
            Fatal,
            Retryable,
            OpenAIError,
        ) as e:  # the calls already answered stay, they were paid
            steps = self.steps(case, recorder)
            return {
                "version": version,
                "error": str(e),
                "steps": steps,
                "cost_usd": total(steps),
            }
        result = score(case.expected, answer.output, SCORING)
        steps = self.steps(case, recorder)
        return {
            "version": version,
            "output": answer.output,
            "raw": None if answer.output is not None else answer.raw,
            "per_field": result["per_field"],
            "score": result["score"],
            "model": answer.model,
            "tokens_in": answer.input_tokens,
            "tokens_out": answer.output_tokens,
            "latency_s": answer.latency_s,
            "cost_usd": total(steps),
            "steps": steps,
        }

    def steps(self, case: Case, recorder: Recorder) -> list[dict]:
        """Each model call the pipeline made, scored on its own; priced as the gate books it (no cached-input price)."""
        out = []
        for r in recorder.responses:
            try:
                output = json.loads(r.choices[0].message.content or "")
            except json.JSONDecodeError:
                output = None
            out.append({
                "output": output,
                "per_field": field_match(case.expected, output, SCORING),
                "tokens_in": r.usage.prompt_tokens,
                "tokens_out": r.usage.completion_tokens,
                "cost_usd": usd(r.model, r.usage.prompt_tokens, r.usage.completion_tokens, self.prices),
            })  # fmt: skip
        return out


def total(steps: list[dict]) -> float | None:
    costs = [s["cost_usd"] for s in steps]
    return None if None in costs else sum(costs)


def handler(desk: Desk):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code: int, body, kind="application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == "/":
                    return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if path == "/api/receipts":
                    versions = {k: {"name": VERSIONS[k][0], "model": c.model, "input": c.input, "hash": desk.hashes[k]}
                                for k, c in desk.configs.items()}  # fmt: skip
                    return self.send(
                        200,
                        {
                            "receipts": desk.listing(),
                            "versions": versions,
                            "fields": FIELDS,
                        },
                    )
                if (
                    path.startswith("/api/receipt/")
                    and "/" not in path[len("/api/receipt/") :]
                ):
                    return self.send(200, desk.describe(path[len("/api/receipt/") :]))
                if path.startswith("/scan/") and path.endswith(".jpg"):
                    case = desk.receipt(path[len("/scan/") : -len(".jpg")])
                    return self.send(
                        200, case.inputs["image"].read_bytes(), "image/jpeg"
                    )
            except (KeyError, FileNotFoundError) as e:
                return self.send(404, {"error": str(e).strip("'\"")})
            except Exception as e:  # noqa: BLE001 - a broken data file: say so instead of dropping the connection
                return self.send(500, {"error": f"{type(e).__name__}: {e}"})
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if (
                self.headers.get_content_type() != "application/json"
            ):  # a browser sends that only from this page
                return self.send(415, {"error": "send application/json"})
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if size < 0:
                    raise ValueError("Content-Length must not be negative")
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise TypeError("send a JSON object")
                if urlparse(self.path).path != "/api/read":
                    return self.send(404, {"error": "not found"})
                times = body.get("times", 1)
                if type(times) is not int or not 1 <= times <= MAX_TIMES:
                    raise ValueError(
                        f"times must be a whole number from 1 to {MAX_TIMES}"
                    )
                runs = [
                    desk.read(str(body["receipt"]), str(body["version"]))
                    for _ in range(times)
                ]
            except KeyError as e:
                return self.send(
                    400, {"error": f"missing or unknown: {str(e).strip(chr(39))}"}
                )
            except (TypeError, ValueError) as e:
                return self.send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 - a broken data file: say so instead of dropping the connection
                return self.send(500, {"error": f"{type(e).__name__}: {e}"})
            self.send(200, {"runs": runs})

        def log_message(self, *args):
            pass

    return Handler


def serve(desk: Desk, host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), handler(desk))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8767)
    p.add_argument(
        "--data",
        type=Path,
        default=DATA,
        help="a SROIE split with box/, img/ and entities/",
    )
    a = p.parse_args()
    if not (a.data / "box").is_dir():
        sys.exit(
            f"no SROIE data in {a.data}: put the Kaggle copy of SROIE in ../../data/SROIE2019/ (README, Setup)"
        )
    timeout = max(
        load_config(HERE / "configs" / f).timeout_s for _, f in VERSIONS.values()
    )
    try:
        client = OpenAI(
            max_retries=0, timeout=timeout
        )  # as the gate's: a run's time is its answer's
    except OpenAIError as e:
        sys.exit(
            f"{e}\nStart it with the key: uv run --env-file ../../.env python -m sroie_example.web"
        )
    ids = yaml.safe_load((HERE / "golden" / "sroie.yaml").read_text())["ids"]
    server = serve(
        Desk(client, a.data, load_prices(HERE / "prices.yaml"), ids), a.host, a.port
    )
    print(
        f"SROIE receipt desk at http://{a.host}:{server.server_port}  (Ctrl+C stops it)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
