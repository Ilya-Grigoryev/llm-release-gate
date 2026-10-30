"""A program for the gate's tests: answers each attempt at a case from a script, without a model.

`params.script` names a JSON file: case id → attempts, each {"answer": {...}, "exit": 0}. The n-th run of a case plays its
n-th attempt, and the last one again after that.
"""

import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
script = Path(request["config"]["params"]["script"])
case = request["case"]["id"]
attempts = json.loads(script.read_text())[case]
counter = script.with_name(f"{script.name}.{case}.n")
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
attempt = attempts[min(n, len(attempts) - 1)]
print(json.dumps(attempt["answer"]))
sys.exit(attempt.get("exit", 0))
