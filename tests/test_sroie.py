import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_release_gate.golden import load_cases
from llm_release_gate.metrics import score
from llm_release_gate.pipeline import PipelineConfig
from llm_release_gate.pipelines.sroie import SCORING, build, cases, parse_box

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
        "12,10,210,10,210,40,12,40,KEDAI UJI\n"
        "14,52,250,52,250,70,14,70,NO.1 3,5 & 7,\n"
        "\n"
    )
    assert parse_box(box) == "KEDAI UJI\nNO.1 3,5 & 7,"


def test_split_cases_score_like_the_golden_set():
    [case] = cases(FIXTURE)
    assert case.scoring == SCORING
    got = {f: f" {v.lower()} " for f, v in case.expected.items()}
    assert score(case.expected, got, case.scoring)["score"] == 1.0


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


@pytest.mark.parametrize("input", ["text", "image"])
def test_golden_cases_run_through_the_pipeline(tmp_path, input):
    [case] = load_cases(Path(__file__).parent / "fixtures" / "golden")
    client = FakeClient()
    answer = build(config(tmp_path, input), client).run(case)
    assert answer.output == OUTPUT


def test_an_empty_label_is_not_scored(tmp_path):
    (tmp_path / "box").mkdir()
    (tmp_path / "entities").mkdir()
    (tmp_path / "box" / "r.txt").write_text("1,1,2,1,2,2,1,2,KEDAI UJI\n")
    (tmp_path / "entities" / "r.txt").write_text(
        '{"company": "KEDAI UJI", "total": ""}'
    )
    [case] = cases(tmp_path)
    assert case.expected == {"company": "KEDAI UJI", "total": None}
    assert score(case.expected, {}, case.scoring)["per_field"]["total"] is None


def test_rescore_writes_copies_and_keeps_the_source(tmp_path, monkeypatch, capsys):
    from llm_release_gate.pipelines import sroie_rescore

    [case] = cases(FIXTURE)
    run = tmp_path / "runs" / "r.jsonl"
    run.parent.mkdir()
    answer = {**case.expected, "date": case.expected["date"] + " 10:42"}
    source = json.dumps({"case": case.id, "output": answer, "hits": {}}) + "\n"
    run.write_text(source)
    out = tmp_path / "typed"
    monkeypatch.setattr(
        "sys.argv", ["x", str(run), "--data", str(FIXTURE), "--write", str(out)]
    )
    sroie_rescore.main()
    copy = json.loads((out / "r.jsonl").read_text())
    assert copy["score"] == 1.0 and copy["rescored"]["variant"] == "typed"
    assert run.read_text() == source
    monkeypatch.setattr(
        "sys.argv", ["x", str(run), "--data", str(FIXTURE), "--write", str(run.parent)]
    )
    with pytest.raises(SystemExit, match="must not overwrite"):
        sroie_rescore.main()


def test_strict_and_text_rescoring_keep_empty_labels(tmp_path):
    (tmp_path / "box").mkdir()
    (tmp_path / "entities").mkdir()
    (tmp_path / "box" / "r.txt").write_text("1,1,2,1,2,2,1,2,KEDAI UJI\n")
    (tmp_path / "entities" / "r.txt").write_text(
        '{"company": "KEDAI UJI", "total": ""}'
    )
    [case] = cases(tmp_path, empty_as_null=False)
    assert case.expected == {"company": "KEDAI UJI", "total": ""}
