"""Pipeline `command`: any program, in any language, as a pipeline.

    pipeline: command
    command: [node, agent.js]

For each run the gate starts the program, writes one JSON request to its stdin and reads one JSON answer from its stdout.

    request: {"case": {"id": ..., "inputs": {name: absolute path}},
              "config": {"model": ..., "prompt": path or {name: path}, "input": ..., "params": {...}}}
    answer:  {"output": {...} or null, "raw": "...", "input_tokens": 0, "output_tokens": 0, "model": "...",
              "trace": {"steps": [{"kind": ..., "actor": ..., ...}], "final_state": ..., "state_change": ..., "stop": ...}}

Everything in the answer but `output` is optional. Exit codes: 0 an answer; 75 try again later (rate limit, timeout
upstream); 78, 126 or 127 stop the whole run (no quota, wrong key, program not found); anything else fails this run.
A program that has not finished within `timeout_s` is killed with its children and the run is retried. A trace on
stdout is kept whatever the exit code. The program never sees the case's expected values.
"""

import json
import os
import signal
import subprocess
import time
from typing import Any

from llm_release_gate import trace
from llm_release_gate.pipeline import Answer, Case, Fatal, PipelineConfig, Retryable

VERSION = 1
RETRY = 75  # sysexits EX_TEMPFAIL
STOP = (78, 126, 127)  # EX_CONFIG; the shell's "cannot execute" and "not found"


def tokens(reply: dict, key: str) -> int:
    value = reply.get(key, 0)
    if not trace.count(value):
        raise ValueError(f"answer: {key} must be a whole number >= 0, got {value!r}")
    return value


def kill(p: subprocess.Popen) -> None:
    """Kill the program and everything it started: a wrapper (`uv run`, `npx`, `sh`) must not leave a paying agent."""
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:  # macOS: EPERM when only a zombie leader is left in the group
        p.kill()
    p.wait()
    for pipe in (p.stdin, p.stdout, p.stderr):
        pipe.close()


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
        sent = json.dumps(self.request(case))
        if (
            t := trace.current()
        ) is not None:  # the record keeps the last attempt's state
            t.final_state = t.state_change = t.stop = None
        try:
            p = subprocess.Popen(
                list(self.config.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,  # its own process group, killed as a whole
            )
        except OSError as e:  # missing or not executable: every run would fail
            raise Fatal(f"cannot start {self.config.command[0]!r}: {e}") from e
        try:
            out, err = p.communicate(sent, timeout=self.config.timeout_s)
        except subprocess.TimeoutExpired:
            kill(p)
            raise Retryable(f"no answer within {self.config.timeout_s:g} s") from None
        # Ctrl+C in the main thread: the program's group does not get the terminal's signal
        except BaseException:
            kill(p)
            raise
        said = f"exit {p.returncode}" + (
            f": {err.strip()[-500:]}" if err.strip() else ""
        )
        if p.returncode != 0:
            keep_trace(out)
            if p.returncode == RETRY:
                raise Retryable(said)
            if p.returncode in STOP:
                raise Fatal(said)
            raise RuntimeError(said)
        try:
            reply = json.loads(out)
        except json.JSONDecodeError:
            raise ValueError(f"answer is not JSON: {out[:200]!r}") from None
        if not isinstance(reply, dict):
            raise TypeError("answer must be a JSON object")
        record(reply.get("trace"))
        output, raw, model = (
            reply.get("output", ...),
            reply.get("raw"),
            reply.get("model"),
        )
        if output is ... or not isinstance(output, dict | None):
            raise TypeError("answer: `output` must be an object or null")
        if model is not None and not isinstance(model, str):
            raise TypeError(f"answer: model must be a string, got {model!r}")
        return Answer(
            output=output,
            raw=raw
            if isinstance(raw, str)
            else json.dumps(output if raw is None else raw, ensure_ascii=False),
            input_tokens=tokens(reply, "input_tokens"),
            output_tokens=tokens(reply, "output_tokens"),
            latency_s=round(time.perf_counter() - start, 3),
            model=model,  # what the program reports; None leaves a run without a trace unpriced
        )


def keep_trace(out: str) -> None:
    """After a failed exit: keep the steps the program paid for; a missing or broken trace leaves a note."""
    try:
        reply = json.loads(out)
    except json.JSONDecodeError:
        return
    if not isinstance(reply, dict):
        return
    try:
        record(reply.get("trace"))
    except (TypeError, ValueError) as e:
        if (t := trace.current()) is not None:
            t.notes.append(f"program trace after a failed exit: {e}")


def record(sent: Any) -> None:
    """Put the program's trace into the current one; a step that breaks the format fails the run."""
    t = trace.current()
    if t is None or sent is None:
        return
    if not isinstance(sent, dict) or not isinstance(sent.get("steps", []), list):
        raise TypeError(
            "answer: trace must be {steps: [...], final_state, state_change, stop}"
        )
    stop = sent.get("stop")
    if stop is not None and not isinstance(stop, str):
        raise TypeError(f"answer: trace stop must be a string, got {stop!r}")
    for step in sent.get("steps", []):
        if not isinstance(step, dict):
            raise TypeError(f"answer: a step must be an object, got {step!r}")
        fields = {
            k: v
            for k, v in step.items()
            if k
            not in ("kind", "actor", "seq", "run_attempt")  # the runner numbers steps
        }
        t.step(step.get("kind"), step.get("actor"), **fields)
    t.final_state = sent.get("final_state", t.final_state)
    t.state_change = sent.get("state_change", t.state_change)
    t.stop = stop if stop is not None else t.stop


def build(config: PipelineConfig) -> Command:
    return Command(config)
