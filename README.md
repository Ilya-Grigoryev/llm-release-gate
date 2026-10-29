# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress. Built: the naive gate (one run per version against a fixed threshold) with a comment on every pull or merge request, cost and latency budgets, traces of agent runs, checks over the answer and the trace, any program as a pipeline, and a [dashboard](#dashboard) of the runs. The statistical rules come next. Three projects use the gate, each in its own repository: [receipt-intake](https://github.com/Ilya-Grigoryev/receipt-intake) reads seller, date, address and total from receipt scans for a bookkeeping team (test receipts from [SROIE](https://rrc.cvc.uab.es/?ch=13), ICDAR 2019), from the OCR text or from the scan; [workbench-support](https://github.com/Ilya-Grigoryev/workbench-support) is the support agent of a coworking space, with tools on its booking system and its own test cases, alone on a ticket or in a chat with a simulated user; [telecom-support](https://github.com/Ilya-Grigoryev/telecom-support) is a mobile carrier's support agent built on the telecom domain of [tau2-bench](https://github.com/sierra-research/tau2-bench): tau2's agent, tools, tasks and evaluator, unchanged.

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

The gate's code imports no pipeline. Give your module a `VERSION` and bump it when your code changes what the model gets. [receipt-intake](https://github.com/Ilya-Grigoryev/receipt-intake) is a whole project set up this way.

### Any program

An application in another language needs no Python adapter. Name the program in the config:

```yaml
pipeline: command
command: [node, agent.js]
model: gpt-5.4-mini-2026-03-17
prompt: prompts/system.md
input: text
```

For each run the gate writes one JSON request to the program's stdin: the case's id and input paths and the version's
model, prompt and params, never the expected values. It reads one JSON answer from stdout: `output`, optionally tokens,
the model and a trace. Exit 75 retries the run; 78, 126 and 127 stop the whole run; any other non-zero code fails it.
[docs/protocol.md](docs/protocol.md) has every field, the trace steps, the exit codes and an example in Node;
[`protocol.schema.json`](src/llm_release_gate/protocol.schema.json) is the schema the gate checks each answer against.

`command` is part of the version and its hash; the program's code is not. When you change the code in a way that
changes what the model gets, bump a number in `params` (`params: {version: 2}`), as a Python module bumps `VERSION`.

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

Each step has a kind (`llm`, `tool`, `message`, `retrieval`) and an actor (`agent`, `user`, `system`, `env`);
[docs/protocol.md](docs/protocol.md#trace) lists the fields of each. A model step holds the model the API reported, tokens, cost, the finish reason and the new output; a tool step holds the name, the
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
# in receipt-intake: the scan version on its golden set, 3 runs per receipt
uv run --env-file .env llm-release-gate run --config configs/sroie-image.yaml --golden data/golden/sroie -k 3 --out runs/image.jsonl
```

## The naive gate

The first gate compares one run per version: it blocks when the candidate's mean score is lower than the base's by more than a threshold, 5 points by default (`--relative` reads it as a percentage of the base mean). It pairs the two files case by case and refuses files with different set hashes, different scorer versions or cases missing from one side. `--golden` rescores both sides from their saved answers with the current scorer, without calling the model. `--prices` takes a YAML of `model: [input, output]` in USD per 1M tokens, or `[input, output, cached input]`, and adds what the decision cost: every successful call of both runs. An agent resends the whole dialog on every call, so most of its input is billed as cached; without the third price, cached tokens cost the full input price. For a traced record that means every model step, the user simulator's included.

Budgets check the candidate: `--max-cost-per-run USD` against its mean cost per run at the gate's prices (it needs
`--prices`), `--max-latency S` against a latency quantile (`--latency-quantile`, 0.95 by default). A run's latency is the
time of the attempt that answered: backoff and failed attempts are left out, and the comment counts the runs that needed
retries. A run that produced no answer (a timeout on every attempt, an error) is not in the budget: it shows up as an
error, and slow runs that time out make the quantile look lower than it is. The quantile comes with a 95 % interval from order statistics, which assumes independent runs and nothing about
their distribution (K repetitions of one case are not independent, so with K > 1 the interval is optimistic); latency
blocks only when the whole interval lies above the limit, so a few slow runs out of many do not, and the comment says
when there are too few runs to decide. The cost per run includes the user simulator's calls. A budget turns a pass into
`budget fail` (exit 12); a quality fail stays a quality fail. The runner stamps each record with the hash of
the price table it used (`prices_hash`), and the JSON report carries the hash of the gate's.

```sh
uv run llm-release-gate gate --base data/runs/base.jsonl --candidate data/runs/candidate.jsonl --markdown comment.md --json verdict.json
```

| Exit code | Meaning |
|---|---|
| 0 | pass |
| 10 | quality fail |
| 11 | inconclusive (not produced by the naive gate) |
| 12 | budget fail: quality passed, a cost or latency limit did not |
| 20 | infra error: the runs cannot be compared, or the tool failed |

Python and argparse keep 1 and 2, so a crash is never read as a verdict.

## Golden set

Each case is a YAML file with its inputs next to it; `src/llm_release_gate/case.schema.json` defines the format.

```sh
uv run llm-release-gate golden validate tests/fixtures/golden
```

`validate` checks the schema, unique ids and that every input exists inside the set, then prints a sha256 over the parsed cases and the input bytes. Reformatting a case keeps the hash. Editing an expectation or an input changes it. With `--manifest` it also fails unless the ids and the hash match. A set that may not go into git (receipt scans in [receipt-intake](https://github.com/Ilya-Grigoryev/receipt-intake)) is rebuilt from a manifest of ids.

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

## Use it in your project

1. Add the gate as a dependency, pinned to a release (`uv add` writes both parts):
   ```toml
   [project]
   dependencies = ["llm-release-gate"]

   [tool.uv.sources]
   llm-release-gate = { git = "https://github.com/Ilya-Grigoryev/llm-release-gate", tag = "v0.1.0-dev.6" }
   ```
2. Write an adapter (`build(config)` and `run(case)`, [Your pipeline](#your-pipeline)) or a program
   ([Any program](#any-program)), a config for the version in production and a golden set.
3. Say what to gate in `gate.yaml` at the project's root:
   ```yaml
   pipelines:
     support:                        # names the comment and the artifact
       config: configs/support.yaml  # the version
       golden: golden/solo           # its test set
   delta: 5                          # block when the mean score drops by more than 5 points
   ```
4. Add the gate to the pull request workflow; put the provider's key in the repository's secrets:
   ```yaml
   on: pull_request
   jobs:
     release-gate:
       runs-on: ubuntu-latest
       permissions: {contents: read, pull-requests: write}
       env:
         OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
       steps:
         - uses: actions/checkout@v7
         - uses: Ilya-Grigoryev/llm-release-gate/setup@v0.1.0-dev.6
           with:
             gate-ssh-key: ${{ secrets.LLM_RELEASE_GATE_KEY }}  # while this repository is private
         - uses: Ilya-Grigoryev/llm-release-gate@v0.1.0-dev.6
   ```

`gate.yaml` ([`project.schema.json`](src/llm_release_gate/project.schema.json)) takes these fields; settings at the top
apply to every pipeline, and a pipeline's own win:

| Field | Meaning |
|---|---|
| `pipelines.NAME.config`, `.golden` | the version's config and the test set's directory, relative to the project |
| `pipelines.NAME.manifest` | ids and hash the set must match, for a set built or fetched outside git |
| `pipelines.NAME.inputs-url` | where the dashboard finds the set's other files (images): a URL with `{path}` or `{name}` |
| `k` | runs per case and version, default 1; the naive rule decides on the first run, budgets use all |
| `delta` | points of mean score the candidate may lose, default 5 |
| `prices` | YAML of `model: [input, output]` USD per 1M tokens, for costs and the cost budget |
| `budgets` | `cost_per_run_usd` (needs `prices`), `latency_s` and `latency_quantile` (default 0.95) |
| `prepare` | a command that readies the project in both trees before their runs, such as `[npm, ci]` |

`setup` installs Python, uv and the project's locked environment. The gate action checks that it can comment, checks
the golden set (against its manifest, if any), and compares the version from the target branch with the one from the
request, in parallel and each with its own code. A request that leaves a pipeline's config, prompts and `VERSION` as
they are gets `unchanged` and costs nothing. A request that adds a pipeline (the target branch has no version of it)
gets `no base version`: the candidate's score, and the check passes. The rules (`delta`, `k`, `budgets`, `prices`) come
from the target branch's `gate.yaml`, so a request cannot loosen its own gate: new rules apply after merge, and the
comment says when a request changes them; protect `gate.yaml` with CODEOWNERS if needed. A pull request from a fork
gets no secrets on GitHub, so the gate cannot call the model: the job fails as `not checked` and says why, and a
maintainer gates it by pushing its branch to the repository. The verdict comes as one comment, edited on later pushes. The action keeps
the records as an artifact, and the golden set's case files and text inputs as a second one for 30 days
(`cases: false` leaves it out), so the [dashboard](#dashboard) can show what each case asked. It fails the job with the
gate's verdict; the job only advises until it is made a required check. With several pipelines in `gate.yaml`, add one
step per pipeline with `pipeline: NAME` and `if: ${{ !cancelled() }}` on all but the first, so a block in one does not
skip the others; each gets its own comment and artifact. A golden set that stays out of git is
fetched or built in a step before the gate; if that step fails, the gate does not run and the request gets no comment.

While this repository is private, only repositories of its owner can use it: the owner shares its actions with them
(Settings → Actions → Access) and gives each a read-only deploy key, passed as `gate-ssh-key`. Other projects wait for
the public release.

Three projects use it, each with its own `.github/workflows/ci.yml`: [receipt-intake](https://github.com/Ilya-Grigoryev/receipt-intake)
(about $0.06 a pull request), [workbench-support](https://github.com/Ilya-Grigoryev/workbench-support) ($0.14) and
[telecom-support](https://github.com/Ilya-Grigoryev/telecom-support) ($0.20).

Outside GitHub Actions the gate's command does the work, from the repository's root. `llm-release-gate pr --base
origin/main --out OUT` runs every pipeline of `gate.yaml` and writes `OUT/NAME` (`--project DIR` when `gate.yaml` is not
at the root, `--list` only checks it). `llm-release-gate comment OUT/NAME/comment.md --name NAME` posts a verdict (on
GitLab with `GITLAB_TOKEN`, a project access token with the `api` scope); `--check` tells beforehand whether the job
can comment, `--dry-run` prints the comment and posts nothing.

## Dashboard

[`dashboard/`](dashboard/) is a web app that keeps the gate's runs: https://llm-release-gate.vercel.app. Install its
GitHub App on the repositories that run the gate action and sign in with GitHub to see each pull request's verdict, the
cases that changed between the two versions, and the answer, checks and steps of every run on both sides. The project's
workflow needs no change; how it works and how to run it is in its [README](dashboard/README.md).

## CI

`.gitlab-ci.yml` and `.github/workflows/ci.yml` run the same checks on every push: lint, the tests and a validation of
the test golden set; for the dashboard lint, types, tests and a build.

## License

MIT, see [`LICENSE`](LICENSE).

## Context

Bachelor thesis at the University of Vienna, Software Architecture group. Supervisor: Dr. Theodoros Theodoropoulos.
