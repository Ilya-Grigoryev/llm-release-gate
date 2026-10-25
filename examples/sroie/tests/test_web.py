"""The receipt desk on a synthetic receipt (the R-004 fixture and a generated 1x1 JPEG), with the model faked: no
network, no SROIE scan."""

import base64
import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest
from sroie_example import web
from test_sroie import EXAMPLE, FIXTURE, OUTPUT, FakeClient, rate_limit

from llm_release_gate.prices import load_prices

PIXEL = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////"
    "////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)
RIGHT = {
    "company": "KEDAI RUNCIT MAJU SDN BHD",
    "date": "3 Oct 2018",
    "address": "x",
    "total": "18.4",
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def desk(tmp_path):
    data = tmp_path / "train"
    for kind in ("box", "entities"):
        (data / kind).mkdir(parents=True)
        shutil.copy(FIXTURE / kind / "sample.txt", data / kind / "sample.txt")
    (data / "img").mkdir()
    (data / "img" / "sample.jpg").write_bytes(PIXEL)
    servers = []

    def start(*contents, client=None):
        d = web.Desk(
            client or FakeClient(*contents),
            data,
            load_prices(EXAMPLE / "prices.yaml"),
            ["sample", "missing"],
        )
        server = web.serve(d, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, body=None, kind="application/json"):
            data = None if body is None else json.dumps(body).encode()
            post = urllib.request.Request(
                base + path, data=data, headers={"Content-Type": kind}
            )
            with urllib.request.urlopen(post) as r:
                raw = r.read()
            return json.loads(raw) if path.startswith("/api/") else raw

        return request

    yield start
    for s in servers:
        s.shutdown()


def test_the_receipts_scans_and_ocr_lines_are_served(desk):
    request = desk()
    assert b"Receipt desk" in request("/")
    listing = request("/api/receipts")
    assert listing["receipts"] == [
        {"id": "sample", "company": "KEDAI RUNCIT MAJU SDN BHD", "total": "18.40"}
    ]
    assert set(listing["versions"]) == {"text", "steps", "image"}
    receipt = request("/api/receipt/sample")
    assert receipt["scan"] and len(receipt["lines"]) == 16
    assert receipt["lines"][0] == {
        "box": [80, 30, 400, 30, 400, 62, 80, 62],
        "text": "KEDAI RUNCIT MAJU SDN BHD",
    }
    assert request("/scan/sample.jpg") == PIXEL


@pytest.mark.parametrize(
    "path",
    [
        "/scan/..%2Fsample.jpg",
        "/scan/missing.jpg",
        "/api/receipt/nope",
        "/api/receipt/a.b",
    ],
)
def test_only_known_receipts_are_served(desk, path):
    request = desk()
    with pytest.raises(urllib.error.HTTPError) as e:
        request(path)
    assert e.value.code == 404


def test_a_read_is_scored_by_the_gate_and_priced(desk):
    request = desk(json.dumps(RIGHT))
    run = request("/api/read", {"receipt": "sample", "version": "text"})["runs"][0]
    assert run["output"] == RIGHT and run["model"] == "gpt-4.1-mini-2025-04-14"
    # dates and totals by value, the address is wrong
    assert run["per_field"] == {
        "company": True,
        "date": True,
        "address": False,
        "total": True,
    }
    assert run["score"] == 0.75 and len(run["steps"]) == 1
    assert run["cost_usd"] == pytest.approx((100 * 0.40 + 20 * 1.60) / 1e6)


def test_two_steps_show_each_call(desk):
    request = desk(json.dumps(OUTPUT), json.dumps(RIGHT))
    run = request("/api/read", {"receipt": "sample", "version": "steps"})["runs"][0]
    assert [s["output"] for s in run["steps"]] == [OUTPUT, RIGHT] and run[
        "output"
    ] == RIGHT
    assert run["tokens_in"] == 200 and run["cost_usd"] == pytest.approx(
        2 * (100 * 0.40 + 20 * 1.60) / 1e6
    )


def test_repeated_reads_and_the_scan_version(desk):
    request = desk(json.dumps(RIGHT))
    runs = request("/api/read", {"receipt": "sample", "version": "image", "times": 3})[
        "runs"
    ]
    assert len(runs) == 3 and all(r["output"] == RIGHT for r in runs)


@pytest.mark.parametrize(
    "body",
    [
        {"receipt": "sample", "version": "text", "times": 9},
        {"receipt": "sample", "version": "nope"},
        {"receipt": "nope", "version": "text"},
        {"version": "text"},
        [1],
    ],
)
def test_bad_reads_are_refused(desk, body):
    request = desk()
    with pytest.raises(urllib.error.HTTPError) as e:
        request("/api/read", body)
    assert e.value.code == 400


def test_without_data_the_page_says_where_to_put_it(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "sroie_example.web", "--data", str(tmp_path)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert p.returncode != 0 and "no SROIE data" in p.stderr


def test_a_post_that_is_not_json_is_refused(desk):
    request = desk()
    with pytest.raises(urllib.error.HTTPError) as e:
        request(
            "/api/read", {"receipt": "sample", "version": "text"}, kind="text/plain"
        )
    assert e.value.code == 415


def test_a_failed_second_call_keeps_the_paid_first_one(desk):
    client = FakeClient(json.dumps(OUTPUT))
    create = client.chat.completions.create

    def second_call_limited(**request):
        if client.requests:
            raise rate_limit()
        return create(**request)

    client.chat.completions.create = second_call_limited
    request = desk(client=client)
    run = request("/api/read", {"receipt": "sample", "version": "steps"})["runs"][0]
    assert (
        "slow down" in run["error"] and len(run["steps"]) == 1 and run["cost_usd"] > 0
    )


def test_a_broken_label_file_is_a_500_not_a_dropped_connection(desk, tmp_path):
    request = desk()
    (tmp_path / "train" / "entities" / "sample.txt").write_text("{not json")
    with pytest.raises(urllib.error.HTTPError) as e:
        request("/api/receipt/sample")
    assert e.value.code == 500
