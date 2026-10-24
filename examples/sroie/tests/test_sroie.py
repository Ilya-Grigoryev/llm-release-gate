import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest
import yaml
from sroie_example import golden, rescore, steps
from sroie_example.pipeline import SCORING, build, cases, parse_box

from llm_release_gate.golden import load_cases, validate
from llm_release_gate.metrics import score
from llm_release_gate.pipeline import (
    Fatal,
    PipelineConfig,
    Retryable,
    config_hash,
    load_config,
    load_pipeline,
)

EXAMPLE = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures"
OUTPUT = {"company": "C", "date": "D", "address": "A", "total": "9.00"}
RAW = json.dumps(OUTPUT)


class FakeClient:
    """Stands in for `openai.OpenAI`: records requests, returns canned completions in turn."""

    def __init__(self, *contents):
        self.requests = []
        self.contents = contents or (RAW,)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        n = len(self.requests)
        content = self.contents[min(n, len(self.contents)) - 1]
        return SimpleNamespace(
            id=f"chatcmpl-{n}",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content), finish_reason="stop"
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
        pipeline="sroie_example.pipeline",
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
    client = FakeClient('{"company": "C", "da')
    answer = build(config(tmp_path, "text"), client).run(cases(FIXTURE)[0])
    assert answer.output is None
    assert answer.raw == '{"company": "C", "da'


def test_unknown_input_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        build(config(tmp_path, "audio"), FakeClient())


@pytest.mark.parametrize("input", ["text", "image"])
def test_a_built_golden_set_runs_through_the_pipeline(tmp_path, monkeypatch, input):
    split = tmp_path / "train"
    shutil.copytree(FIXTURE, split)
    (split / "img").mkdir()
    (split / "img" / "sample.jpg").write_bytes(b"\xff\xd8not a real jpeg")
    out, manifest = tmp_path / "golden", tmp_path / "sroie.yaml"
    argv = ["x", "--src", str(split), "-n", "1", "--skip", "0", "--out", str(out)]
    monkeypatch.setattr("sys.argv", [*argv, "--manifest", str(manifest)])
    golden.main()
    set_hash, errors = validate(out)
    assert not errors and yaml.safe_load(manifest.read_text())["sha256"] == set_hash
    [case] = load_cases(out)
    answer = build(config(tmp_path, input), FakeClient()).run(case)
    assert answer.output == OUTPUT


@pytest.mark.parametrize("input", ["text", "image"])
def test_the_ci_smoke_set_runs_through_the_pipeline(tmp_path, input):
    # the model-call job in CI runs this pipeline on the gate's own fixture
    [case] = load_cases(EXAMPLE.parent.parent / "tests" / "fixtures" / "golden")
    answer = build(config(tmp_path, input), FakeClient()).run(case)
    assert answer.output == OUTPUT


@pytest.mark.parametrize(
    "name, input",
    [("sroie-text", "text"), ("sroie-image", "image"), ("sroie-steps", "text")],
)
def test_shipped_configs_load_through_the_gate(name, input):
    config = load_config(EXAMPLE / "configs" / f"{name}.yaml")
    assert config.pipeline.startswith("sroie_example.") and config_hash(config)
    assert load_pipeline(config, client=object()).config.input == input


def test_one_and_two_steps_are_different_versions():
    one, two = (
        load_config(EXAMPLE / "configs" / f"{n}.yaml")
        for n in ("sroie-text", "sroie-steps")
    )
    assert two.prompt["extract"] == one.prompt
    assert config_hash(one) != config_hash(two)


CHECKED = {**OUTPUT, "date": "25/12/2018", "total": "9.00"}


def steps_config(tmp_path, input="text"):
    (tmp_path / "check.md").write_text("Check fields.")
    single = config(tmp_path, input)
    named = {"extract": single.prompt, "check": tmp_path / "check.md"}
    return replace(single, pipeline="sroie_example.steps", prompt=named)


def test_steps_send_the_first_answer_to_the_check(tmp_path):
    client = FakeClient(RAW, json.dumps(CHECKED))
    answer = steps.build(steps_config(tmp_path), client).run(cases(FIXTURE)[0])
    first, second = client.requests
    assert first["messages"][0]["content"] == "Extract fields."
    assert second["messages"][0]["content"] == "Check fields."
    receipt = first["messages"][1]["content"]
    assert (
        second["messages"][1]["content"]
        == f"{receipt}\n\nFields from the first step:\n{RAW}"
    )
    assert answer.output == CHECKED and answer.request_id == "chatcmpl-2"
    assert (answer.input_tokens, answer.output_tokens) == (200, 40)


def test_steps_show_the_scan_to_the_check(tmp_path):
    scan = tmp_path / "scan.jpg"
    scan.write_bytes(b"\xff\xd8not a real jpeg")
    case = cases(FIXTURE)[0]
    case = replace(case, inputs={**case.inputs, "image": scan})
    client = FakeClient(RAW, json.dumps(CHECKED))
    steps.build(steps_config(tmp_path, "image"), client).run(case)
    image, fields = client.requests[1]["messages"][1]["content"]
    assert image["type"] == "image_url" and fields["text"].endswith(RAW)


def test_steps_stop_when_the_first_answer_is_not_json(tmp_path):
    client = FakeClient('{"company": "C", "da')
    answer = steps.build(steps_config(tmp_path), client).run(cases(FIXTURE)[0])
    assert len(client.requests) == 1 and answer.output is None


def test_each_pipeline_refuses_the_other_prompt_shape(tmp_path):
    with pytest.raises(ValueError, match="extract, check"):
        steps.build(config(tmp_path, "text"), FakeClient())
    with pytest.raises(ValueError, match="one file"):
        build(steps_config(tmp_path), FakeClient())


def rate_limit(code=None):
    # Built without an HTTP response: only the class and the code matter to the pipeline.
    error = openai.RateLimitError.__new__(openai.RateLimitError)
    Exception.__init__(error, "slow down")
    error.code = code
    return error


@pytest.mark.parametrize(
    "code, expected", [(None, Retryable), ("insufficient_quota", Fatal)]
)
def test_rate_limits_map_to_retry_or_stop(tmp_path, code, expected):
    def create(**request):
        raise rate_limit(code)

    client = FakeClient()
    client.chat.completions.create = create
    with pytest.raises(expected):
        build(config(tmp_path, "text"), client).run(cases(FIXTURE)[0])


@pytest.mark.parametrize(
    "company, chain",
    [
        ("TEST MART (M) SDN BHD", "TEST MART"),
        ("UJI BAKERIES (KL) SDN BHD", "UJI BAKERIES"),
        ("42 DEMO MART S/B", "42 DEMO MART"),
        ("A.B.C. TEA & CO (M) SDN. BHD.", "ABC TEA & CO"),
    ],
)
def test_store_chain(company, chain):
    assert golden.store(company) == chain


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
    rescore.main()
    copy = json.loads((out / "r.jsonl").read_text())
    assert copy["score"] == 1.0 and copy["rescored"]["variant"] == "typed"
    assert run.read_text() == source
    monkeypatch.setattr(
        "sys.argv", ["x", str(run), "--data", str(FIXTURE), "--write", str(run.parent)]
    )
    with pytest.raises(SystemExit, match="must not overwrite"):
        rescore.main()


def test_strict_and_text_rescoring_keep_empty_labels(tmp_path):
    (tmp_path / "box").mkdir()
    (tmp_path / "entities").mkdir()
    (tmp_path / "box" / "r.txt").write_text("1,1,2,1,2,2,1,2,KEDAI UJI\n")
    (tmp_path / "entities" / "r.txt").write_text(
        '{"company": "KEDAI UJI", "total": ""}'
    )
    [case] = cases(tmp_path, empty_as_null=False)
    assert case.expected == {"company": "KEDAI UJI", "total": ""}


@pytest.mark.parametrize(
    "variant, total", [("typed", None), ("text", False), ("strict", False)]
)
def test_rescore_counts_an_empty_label_only_outside_the_gate(
    tmp_path, monkeypatch, variant, total
):
    (tmp_path / "box").mkdir()
    (tmp_path / "entities").mkdir()
    (tmp_path / "box" / "r.txt").write_text("1,1,2,1,2,2,1,2,KEDAI UJI\n")
    (tmp_path / "entities" / "r.txt").write_text(
        '{"company": "KEDAI UJI", "total": ""}'
    )
    run = tmp_path / "r.jsonl"
    answer = {"company": "KEDAI UJI", "total": "8.20"}
    run.write_text(json.dumps({"case": "r", "output": answer}) + "\n")
    out = tmp_path / "out"
    argv = ["x", str(run), "--data", str(tmp_path), "--variant", variant]
    monkeypatch.setattr("sys.argv", [*argv, "--write", str(out)])
    rescore.main()
    copy = json.loads((out / "r.jsonl").read_text())
    assert copy["hits"]["total"] is total
    assert copy["scorer_version"].endswith("" if variant == "typed" else f"+{variant}")
