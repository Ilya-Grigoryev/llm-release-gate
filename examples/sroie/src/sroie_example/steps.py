"""SROIE in two LLM steps: extract the four fields, then check them against the receipt."""

import json
from dataclasses import replace

from openai import OpenAI

from llm_release_gate.pipeline import Answer, Case, PipelineConfig
from sroie_example import pipeline
from sroie_example.pipeline import SroiePipeline

# Both calls go through pipeline.py, so its VERSION is part of this one.
VERSION = (pipeline.VERSION, 1)  # bump the 1 when what step 2 sees changes
STEPS = ("extract", "check")


class StepsPipeline(SroiePipeline):
    """Step 2 gets the receipt and step 1's fields. A retry repeats both steps."""

    def __init__(self, config: PipelineConfig, client: OpenAI):
        prompts = config.prompt
        if not isinstance(prompts, dict) or set(prompts) != set(STEPS):
            raise ValueError(f"prompt must name one file per step: {', '.join(STEPS)}")
        super().__init__(replace(config, prompt=prompts["extract"]), client)
        self.check = prompts["check"].read_text()

    def run(self, case: Case) -> Answer:
        """Step 2's answer with the tokens and time of both steps; step 1's if it is not JSON."""
        receipt = self.content(case)
        first = self.ask(self.prompt, receipt)
        if first.output is None:
            return first
        fields = "Fields from the first step:\n" + json.dumps(
            first.output, ensure_ascii=False
        )
        second = self.ask(
            self.check,
            f"{receipt}\n\n{fields}"
            if isinstance(receipt, str)
            else [*receipt, {"type": "text", "text": fields}],
        )
        return replace(
            second,
            input_tokens=first.input_tokens + second.input_tokens,
            output_tokens=first.output_tokens + second.output_tokens,
            reasoning_tokens=first.reasoning_tokens + second.reasoning_tokens,
            latency_s=round(first.latency_s + second.latency_s, 3),
        )


def build(config: PipelineConfig, client: OpenAI | None = None) -> StepsPipeline:
    # The runner retries and counts retries, so the SDK must not retry on its own.
    return StepsPipeline(
        config, client or OpenAI(max_retries=0, timeout=config.timeout_s)
    )
