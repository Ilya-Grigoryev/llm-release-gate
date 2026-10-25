"""Pipeline `command`: any program, in any language, as a pipeline.

    pipeline: command
    command: [node, agent.js]

For each run the gate starts the program, writes one JSON request to its stdin and reads one JSON answer from its stdout.

    request: {"case": {"id": ..., "inputs": {name: absolute path}},
              "config": {"model": ..., "prompt": path or {name: path}, "input": ..., "params": {...}}}
    answer:  {"output": ..., "raw": "...", "input_tokens": 0, "output_tokens": 0, "model": "...",
              "trace": {"steps": [{"kind": ..., "actor": ..., ...}], "final_state": ..., "state_change": ..., "stop": ...}}

Everything in the answer but `output` is optional. Exit codes: 0 an answer; 75 try again later (rate limit, timeout
upstream); 78 stop the whole run (no quota, wrong key); anything else, or no answer within `timeout_s`, fails this run.
The program never sees the case's expected values.
"""

import json
import subprocess
import time
from typing import Any

from llm_release_gate import trace
from llm_release_gate.pipeline import Answer, Case, Fatal, PipelineConfig, Retryable

VERSION = 1
RETRY, STOP = 75, 78  # sysexits: EX_TEMPFAIL, EX_CONFIG


def count(reply: dict, key: str) -> int:
    value = reply.get(key, 0)
    if type(value) is not int or value < 0:
        raise ValueError(f"answer: {key} must be a whole number >= 0, got {value!r}")
    return value


class Command:
    def __init__(self, config: PipelineConfig):
        if not config.command:
            raise ValueError(
                "pipeline command needs `command: [program, argument, ...]`"
            )
        self.config = config

    def request(self, case: Case) -> dict:
        prompt = self.config.prompt
        return {
            "case": {
                "id": case.id,
                "inputs": {k: str(p.resolve()) for k, p in case.inputs.items()},
            },
            "config": {
                "model": self.config.model,
                "prompt": str(prompt.resolve())
                if not isinstance(prompt, dict)
                else {k: str(p.resolve()) for k, p in prompt.items()},
                "input": self.config.input,
                "params": self.config.params,
            },
        }

    def run(self, case: Case) -> Answer:
        start = time.perf_counter()
        try:
            p = subprocess.run(
                list(self.config.command),
                input=json.dumps(self.request(case)),
                capture_output=True,
                text=True,
                timeout=self.config.timeout_s,
                check=False,  # the exit code is read below
            )
        except subprocess.TimeoutExpired:
            raise Retryable(f"no answer within {self.config.timeout_s:g} s") from None
        except (
            OSError
        ) as e:  # the program is missing or not executable: every run would fail
            raise Fatal(f"cannot start {self.config.command[0]!r}: {e}") from e
        said = p.stderr.strip()[-500:]
        if p.returncode == RETRY:
            raise Retryable(said or f"exit {RETRY}")
        if p.returncode == STOP:
            raise Fatal(said or f"exit {STOP}")
        if p.returncode != 0:
            raise RuntimeError(f"exit {p.returncode}: {said}")
        try:
            reply = json.loads(p.stdout)
        except json.JSONDecodeError:
            raise ValueError(f"answer is not JSON: {p.stdout[:200]!r}") from None
        if not isinstance(reply, dict) or "output" not in reply:
            raise ValueError("answer must be a JSON object with `output`")
        record(reply.get("trace"))
        return Answer(
            output=reply["output"],
            raw=str(reply.get("raw", p.stdout)),
            input_tokens=count(reply, "input_tokens"),
            output_tokens=count(reply, "output_tokens"),
            latency_s=round(time.perf_counter() - start, 3),
            model=str(reply.get("model", self.config.model)),
        )


def record(sent: Any) -> None:
    """Put the program's trace into the current one; a step that breaks the format fails the run."""
    t = trace.current()
    if t is None or sent is None:
        return
    if not isinstance(sent, dict) or not isinstance(sent.get("steps", []), list):
        raise TypeError(
            "answer: trace must be {steps: [...], final_state, state_change, stop}"
        )
    for step in sent.get("steps", []):
        if not isinstance(step, dict):
            raise TypeError(f"answer: a step must be an object, got {step!r}")
        fields = {
            k: v
            for k, v in step.items()
            if k not in ("kind", "actor", "seq", "run_attempt")
        }
        t.step(step.get("kind"), step.get("actor"), **fields)
    t.final_state = sent.get("final_state", t.final_state)
    t.state_change = sent.get("state_change", t.state_change)
    t.stop = sent.get("stop", t.stop)


def build(config: PipelineConfig) -> Command:
    return Command(config)
