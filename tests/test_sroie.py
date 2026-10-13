import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_release_gate.pipeline import PipelineConfig
from llm_release_gate.pipelines.sroie import build, cases, field_hits, parse_box

FIXTURE = Path(__file__).parent / "fixtures" / "sroie"
OUTPUT = {"company": "C", "date": "D", "address": "A", "total": "9.00"}
RAW = json.dumps(OUTPUT)


class FakeClient:
    """Stands in for `openai.OpenAI`: records requests, returns a canned completion."""

    def __init__(self, content=RAW):
        self.requests = []
        self.content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            id="chatcmpl-1",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content), finish_reason="stop"
                )
            ],
            model="gpt-4.1-mini-2025-04-14",
            system_fingerprint="fp_test",
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )


def config(tmp_path, input):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Extract fields.")
    return PipelineConfig(
        pipeline="sroie",
        model="gpt-4.1-mini-2025-04-14",
        prompt=prompt,
        input=input,
        params={"temperature": 0, "seed": 0},
    )


def test_parse_box_keeps_commas_in_text():
    box = (
        "72,25,326,25,326,64,72,64,TAN WOON YANN\n"
        "110,144,383,144,383,163,110,163,NO.53 55,57 & 59,\n"
        "\n"
    )
    assert parse_box(box) == "TAN WOON YANN\nNO.53 55,57 & 59,"


def test_field_hits_ignores_case_and_spacing():
    expected = {"company": "BOOK TA .K SDN BHD", "date": "25/12/2018", "total": "9.00"}
    got = {"company": "book ta .k  sdn bhd", "date": "25/12/2018", "address": "X"}
    assert field_hits(expected, got) == {
        "company": True,
        "date": True,
        "address": False,
        "total": False,
    }


def test_cases_read_a_split():
    [case] = cases(FIXTURE)
    assert case.id == "sample"
    assert case.inputs["text"] == FIXTURE / "box" / "sample.txt"
    assert set(case.expected) == {"company", "date", "address", "total"}


def test_text_input_sends_ocr_lines(tmp_path):
    client = FakeClient()
    answer = build(config(tmp_path, "text"), client).run(cases(FIXTURE)[0])
    [request] = client.requests
    assert request["model"] == "gpt-4.1-mini-2025-04-14"
    assert request["seed"] == 0 and request["temperature"] == 0
    assert request["messages"][0]["content"] == "Extract fields."
    user = request["messages"][1]["content"]
    assert isinstance(user, str) and not user.startswith("72,")
    assert answer.output == OUTPUT
    assert (answer.input_tokens, answer.output_tokens) == (100, 20)
    assert answer.model == "gpt-4.1-mini-2025-04-14"
    assert answer.fingerprint == "fp_test"
    assert answer.request_id == "chatcmpl-1"


def test_image_input_sends_the_scan(tmp_path):
    scan = tmp_path / "scan.jpg"
    scan.write_bytes(b"\xff\xd8not a real jpeg")
    case = cases(FIXTURE)[0]
    case = replace(case, inputs={**case.inputs, "image": scan})
    client = FakeClient()
    build(config(tmp_path, "image"), client).run(case)
    [part] = client.requests[0]["messages"][1]["content"]
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_unparsable_answer_keeps_raw_text(tmp_path):
    client = FakeClient(content='{"company": "C", "da')
    answer = build(config(tmp_path, "text"), client).run(cases(FIXTURE)[0])
    assert answer.output is None
    assert answer.raw == '{"company": "C", "da'


def test_unknown_input_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        build(config(tmp_path, "audio"), FakeClient())
