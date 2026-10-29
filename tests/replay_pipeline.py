"""A pipeline outside the gate's package for its tests: replays recorded answers, no key needed."""

import json
import threading
import time
from pathlib import Path

from llm_release_gate.pipeline import Answer

ANSWERS = Path(__file__).parent / "fixtures" / "replay" / "synth-001.jsonl"


class Replay:
    """A recorded provider: replays model answers from a fixture, in order, per case."""

    def __init__(self, fail=None, delay=0.0, answers=None):
        lines = ANSWERS.read_text().splitlines()
        self.answers = answers or [Answer(**json.loads(line)) for line in lines]
        self.calls = []
        self.fail = fail or (lambda case, n: None)
        self.delay = delay
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def run(self, case):
        with self.lock:
            n = sum(c == case.id for c in self.calls)
            self.calls.append(case.id)
            number = len(self.calls)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            self.fail(case, number)
            return self.answers[n % len(self.answers)]
        finally:
            with self.lock:
                self.active -= 1


def build(config):
    return Replay()
