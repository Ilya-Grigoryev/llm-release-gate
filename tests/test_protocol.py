import json
import re
import shutil
from pathlib import Path

import pytest

from llm_release_gate import protocol
from llm_release_gate.command import Command
from llm_release_gate.golden import load_cases
from llm_release_gate.pipeline import load_config

ROOT = Path(__file__).parent.parent
DOC = (ROOT / "docs" / "protocol.md").read_text()
FIXTURES = Path(__file__).parent / "fixtures"


def blocks(language):
    return re.findall(rf"```{language}\n(.*?)```", DOC, re.DOTALL)


@pytest.mark.parametrize("example", blocks("json"))
def test_the_documents_examples_follow_the_schema(example):
    sent = json.loads(example)
    assert protocol.errors(sent, "request" if "case" in sent else "answer") == []


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_documents_node_program_answers_through_the_gate(tmp_path):
    [program] = blocks("js")
    (tmp_path / "agent.js").write_text(program)
    config = tmp_path / "command.yaml"
    config.write_text(
        f"command: [node, {tmp_path / 'agent.js'}]\n"
        f"model: m-2026-01-01\nprompt: {FIXTURES / 'prompt.md'}\ninput: text\n"
    )
    [case] = load_cases(FIXTURES / "golden")
    assert Command(load_config(config)).run(case).output == {"id": case.id}


@pytest.mark.parametrize(
    "answer, error",
    [
        (
            {"output": {}, "input_tokens": 3.0},
            "input_tokens: 3.0 is not of type 'integer'",
        ),
        (
            {"output": {}, "output_tokens": True},
            "output_tokens: True is not of type 'integer'",
        ),
        (
            {"output": {}, "trace": {"steps": [{"kind": "tool", "actor": "env"}]}},
            "missing trace.steps.0.args",
        ),
        (
            {
                "output": {},
                "trace": {
                    "steps": [
                        {
                            "kind": "llm",
                            "actor": "agent",
                            "status": "error",
                            "error": "x",
                            "attempt": 0,
                        }
                    ]
                },
            },
            "trace.steps.0.attempt: 0 is less than the minimum of 1",
        ),
    ],
)
def test_counts_are_integer_literals_and_steps_carry_their_fields(answer, error):
    assert error in protocol.errors(answer, "answer")


def test_a_decimal_is_not_a_json_number():
    from decimal import Decimal

    step = {"kind": "llm", "actor": "agent", "status": "ok", "model": "m"}
    step |= {"tokens_in": 1, "tokens_out": 1, "cost_usd": Decimal("0.01")}
    assert protocol.errors(step, "step") == [
        "cost_usd: Decimal('0.01') is not of type 'number', 'null'"
    ]
