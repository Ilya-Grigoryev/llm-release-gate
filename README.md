# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress. Built: the naive gate (one run per version against a fixed threshold) with a comment on every pull or merge request, traces of agent runs, checks over the answer and the trace, and any program as a pipeline. The statistical rules and the cost and latency budgets come next. [`examples/sroie/`](examples/sroie/) extracts company, address, date and total from receipts in [SROIE](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019), from the OCR text or from the scan. [`examples/support-agent/`](examples/support-agent/) is a tool-using support agent over a mock database, with its own test cases, under the gate alone on a ticket or in a chat with a simulated user.

[`docs/design.md`](docs/design.md) describes the parts, the flow of a merge request and the record of a run.

## Your pipeline

The gate runs any Python module with a `build(config)` function. `build` returns an object whose `run(case)` gives back an `Answer` (`src/llm_release_gate/pipeline.py`): the parsed output, the raw text, tokens, latency and the model the provider reported. Raise `Retryable` when the same call may succeed later (rate limit, timeout) and `Fatal` when no call can (out of quota, wrong key).

Name the module by its import path in the config of each version:

```yaml
pipeline: my_app.gate_adapter   # installed, or importable from where you run the gate
model: gpt-4.1-mini-2025-04-14  # a dated snapshot if there is one
prompt: prompts/extract.md      # relative to this file, or named files: {extract: a.md, check: b.md}
input: text
params: {temperature: 0}
```

Prefer a dated snapshot. A name without a date (`gpt-6-luna`) works, but the provider may change the model behind it,
so the gate takes three precautions: every record keeps the requested model next to the one the provider reports and the
time, the gate's comment warns about it, and the gate refuses to compare two versions whose runs, taken together, have a
pause longer than an hour, or that asked for the same model and got different ones from the provider (or runs that do
not say which one they got: report `model`).

The gate's code imports no pipeline. Give your module a `VERSION` and bump it when your code changes what the model gets. [`examples/sroie/`](examples/sroie/) is a whole project set up this way.

### Any program

An application in another language needs no Python adapter. Name the program in the config:

```yaml
pipeline: command
command: [node, agent.js]
model: gpt-5.4-mini-2026-03-17
prompt: prompts/system.md
input: text
```

For each run the gate starts the program in the runner's working directory (relative paths in `command` resolve from
there) and writes one JSON request to its stdin:

```json
{"case": {"id": "synth-001", "inputs": {"text": "/abs/path/synth-001.txt"}},
 "config": {"model": "gpt-5.4-mini-2026-03-17", "prompt": "/abs/path/system.md", "input": "text", "params": {}}}
```

`prompt` is a path, or a map of paths when the config names several prompts. The program never gets the expected
values. It writes one JSON object to stdout and its logs to stderr:

```json
{"output": {"total": "12.50"}, "raw": "...", "input_tokens": 0, "output_tokens": 0, "model": "...",
 "trace": {"steps": [], "final_state": null, "state_change": null, "stop": "done"}}
```

Only `output` (an object or `null`) is required. `raw` defaults to `output` as JSON. Report `model` as the provider
returned it; a run with neither `model` nor model steps in its trace stays unpriced. The trace uses the format below; the
runner numbers its steps. The exit code decides the rest:

| Exit | Meaning |
|---|---|
| 0 | the answer |
| 75 | try again later (rate limit, upstream timeout): the runner backs off and retries |
| 78, 126, 127 | stop the whole run (no quota, wrong key, program not found) |
| any other | this run fails |

The gate keeps a trace the program printed before a failed exit, so paid steps count. `timeout_s` bounds the whole
program. The program runs in its own process group (POSIX only); on timeout the gate kills the group, loses that
attempt's trace and retries. A child that leaves the group (`setsid`, a container started with `docker run`) survives
the kill: stop it in the program.

`command` is part of the version and its hash; the program's code is not. When you change the code in a way that
changes what the model gets, bump a number in `params` (`params: {version: 2}`), as a Python module bumps `VERSION`.
[`tests/fixtures/command/agent.sh`](tests/fixtures/command/agent.sh) is a small example in shell.

## Traces

A tool-using agent makes many calls per case. The runner keeps a trace for each run, and your adapter records into it
without touching your application:

```python
from llm_release_gate import trace


class Adapter:
    def __init__(self, config):
        self.client = trace.openai_client(OpenAI())  # a step per model call

    def run(self, case):
        world = load_world(case)
        world.call = trace.wrap_tool(world.call)  # a step per tool call
        reply = my_agent(self.client, world, case)
        if (t := trace.current()) is not None:  # None outside the runner
            t.final_state, t.state_change, t.stop = world.state(), world.diff(), "done"
        return Answer(...)
```

Each step has a kind (`llm`, `tool`, `message`, `retrieval`) and an actor (`agent`, `user`, `system`, `env`). A model step
holds the model the API reported, tokens, cost, the finish reason and the new output; a tool step holds the name, the
arguments, a status and the result or error. Wrap a user simulator's client with `actor="user"` to keep its cost apart from
the agent's. Record what the wrappers cannot see with `trace.current().step(kind, actor, ...)`. Tool calls you do not wrap
are rebuilt from the `tool` messages your agent sends back, with status `unknown`. Only `chat.completions.create` is
recorded: a streamed call leaves a note in the trace, and other methods (Responses API, `parse`, raw responses) pass
through unrecorded. The current trace
belongs to the thread that runs the case; give `trace=` to the wrappers for calls from threads your application starts.

The record gets the trace, tokens and cost per actor (`usage`) and the wall-clock time (`wall_s`). A run that fails halfway
keeps the steps it paid for. A run the runner retries keeps every attempt's steps under `run_attempt`; checks look at the
last attempt, the cost counts all of them. A run stopped by a `Fatal` error is written too when it paid for steps. `wall_s` includes the
runner's backoff between attempts. A pipeline that records nothing writes `trace: null`, as before.

## Running a version

Each pipeline version is a YAML file: pipeline module, model (a dated snapshot if there is one), prompt file (or named prompt files for a pipeline with several steps), input, API parameters and, optionally, `max_retries` (default 5) and `timeout_s` (default 60). Its hash covers every field, the bytes of each prompt and the module's `VERSION`; key order, YAML formatting and `0` versus `0.0` do not change it.

The runner calls the pipeline K times per case of a golden set and appends one JSON record per call, stamped with the config hash, the set hash and the scorer version. A rerun pays only for what is missing. The runner retries rate limits, timeouts and server errors with backoff 1, 2, 4... s and stops when the account is out of quota. `--prices` puts a list price on each model step of a trace; the raw provider responses go to `<stem>.native.jsonl`.

```sh
# from examples/sroie: the scan on the SROIE golden set, 3 runs per receipt
uv run --env-file ../../.env python -m llm_release_gate.runner --config configs/sroie-image.yaml --golden ../../data/golden/sroie -k 3 --out ../../data/runs/image.jsonl
```

## The naive gate

The first gate compares one run per version: it blocks when the candidate's mean score is lower than the base's by more than a threshold, 5 points by default (`--relative` reads it as a percentage of the base mean). It pairs the two files case by case and refuses files with different set hashes, different scorer versions or cases missing from one side. `--golden` rescores both sides from their saved answers with the current scorer, without calling the model. `--prices` takes a YAML of `model: [input, output]` in USD per 1M tokens, or `[input, output, cached input]`, and adds what the decision cost: every successful call of both runs. An agent resends the whole dialog on every call, so most of its input is billed as cached; without the third price, cached tokens cost the full input price. For a traced record that means every model step, the user simulator's included.

```sh
uv run python -m llm_release_gate.gate --base data/runs/base.jsonl --candidate data/runs/candidate.jsonl --markdown comment.md --json verdict.json
```

| Exit code | Meaning |
|---|---|
| 0 | pass |
| 10 | quality fail |
| 11 | inconclusive (not produced by the naive gate) |
| 12 | budget fail (not yet checked) |
| 20 | infra error: the runs cannot be compared, or the tool failed |

Python and argparse keep 1 and 2, so a crash is never read as a verdict.

## Golden set

Each case is a YAML file with its inputs next to it; `src/llm_release_gate/case.schema.json` defines the format.

```sh
uv run python -m llm_release_gate.golden validate tests/fixtures/golden
```

`validate` checks the schema, unique ids and that every input exists inside the set, then prints a sha256 over the parsed cases and the input bytes. Reformatting a case keeps the hash. Editing an expectation or an input changes it. With `--manifest` it also fails unless the ids and the hash match. The SROIE set stays out of git; [`examples/sroie/`](examples/sroie/) rebuilds it from a manifest of receipt ids.

## Scoring

A case's `scoring` block picks the scorer. `field_match` compares each expected field with the answer. `fields` gives a field a type: a `date` or a `number` is compared by value (`25/12/2018` matches `25/12/2018 8:13 PM`, `9.00` matches `RM 9.0`), a `string` as text after the listed normalisers (`whitespace`, `casefold`). A label that does not parse is compared as text. A field expected as `null` is not scored. The case score is the share of right fields among the scored ones. Records keep the scorer version, and runs scored by different versions are not compared.

`checks` runs a list of checks over the answer and the trace. Each gives true or false, a share, or nothing when it does not apply; the record keeps every result, and `aggregate` turns them into the case score: `mean` (default) or `all` (1 only if every scored check passes).

```yaml
scoring:
  method: checks
  aggregate: all
  checks:
    - {id: state, kind: state, key: state_change}    # equals expected.state_change
    - {id: acted, kind: active}                      # the agent called a tool itself
    - {id: verified, kind: order, first: find_member, then: [create_booking, cancel_booking]}
    - {id: no-big-credit, kind: not_called, tool: issue_credit, args: {amount_eur: {gt: 30}}}
    - {id: steps, kind: max_steps, max: 12}
    - {id: reply, kind: regex, field: reply, pattern: "B-\\d+"}
```

Answer checks: `field_match`, `exact`, `contains`, `regex`, `number` (with `tol`), `json_schema`, `refusal`. Trace checks: `called` and `not_called` (with argument conditions `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`), `order`, `max_steps`, `active`, `actions` (one result per expected action), `state`, `doc_found` (the share of expected documents retrieved). `function` calls your own `module:function` with the expected values, the answer, the trace and the check. Trace checks look at the steps of the runner's last attempt, at the agent unless `actor` says otherwise, and fail when the run has no trace.

A check compares against its own `value` or against the case's expected value at the path `expected` (`field_match` reads `expected.fields` by default); `field` picks a part of the answer. A check over many items reports one result each, as `id.field` or `id.N:tool`. `exact` ignores surrounding spaces, `contains` also ignores case; `number` takes plain numbers and amounts such as `RM 7.70`. In `args`, a value must match exactly and a mapping is a set of operators (`{eq: {...}}` matches a mapping). `called` and `active` count calls that went through; `not_called` also counts a call the tool refused, since the attempt is the conduct being checked. `max_steps` passes a run with no model calls. A missing answer is not a refusal. `aggregate` applies to `field_match` too; `all` needs every scored result to be full. In `args`, `gt`, `gte`, `lt` and `lte` take a number and `in` a list of allowed values. `actions` lists `{tool, args}` (or names them with `expected`), `doc_found` takes `ids`, `state` takes `key` (`final_state` or `state_change`). `order` looks at calls that went through or whose outcome the trace does not know (`unknown`). A `function` check may carry its own keys and must return true, false, a share or nothing. `golden validate` checks every configuration against the case's expected values without running it, and rejects keys a check does not know.

## CI

`.gitlab-ci.yml` and `.github/workflows/ci.yml` run the same checks on every push: lint, the tests of the gate and of each example, and a validation of the test golden set.

On a pull or merge request, `release-gate` gates the SROIE example. `ci/gate.sh` runs the version from the target branch and the one from the request on the golden set, in parallel and each with its own code, then the gate. `python -m llm_release_gate.comment` posts the verdict as one comment and edits it on later pushes. The job only advises until you make it a required check (GitHub) or drop `allow_failure` (GitLab). A run costs about $0.06: 30 scans per version.

It needs:

- `OPENAI_API_KEY` as a GitHub secret or a masked GitLab CI/CD variable;
- the golden set archive, `sroie.tar.gz` of `data/golden/sroie`: the release `golden-sroie-9436cc87` on GitHub, the generic package `golden-sroie/9436cc87` on GitLab; the job checks it against `examples/sroie/golden/sroie.yaml`;
- on GitLab, `GITLAB_TOKEN`: a project access token with the `api` scope, to write the comment.

`python -m llm_release_gate.comment comment.md --dry-run` prints the comment and posts nothing.

## License

MIT, see [`LICENSE`](LICENSE). The SROIE data is not part of this repository and keeps its own terms.

## Context

Bachelor thesis at the University of Vienna, Software Architecture group. Supervisor: Dr. Theodoros Theodoropoulos.
