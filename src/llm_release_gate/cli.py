"""`llm-release-gate COMMAND`: the gate's commands under one name."""

import sys

from llm_release_gate import comment, gate, golden, pr, runner

COMMANDS = {
    "pr": pr.main,
    "run": runner.main,
    "gate": gate.main,
    "golden": golden.main,
    "comment": comment.main,
}
USAGE = f"usage: llm-release-gate {{{','.join(COMMANDS)}}} ...\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        sys.stderr.write(USAGE)
        return 2
    return COMMANDS[args[0]](args[1:]) or 0
