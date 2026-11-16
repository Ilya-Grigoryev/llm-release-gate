# llm-release-gate

A CI gate for LLM pipelines. On every merge request it runs the base and the candidate version of a pipeline over a fixed test set and blocks the merge if:

- quality dropped by more than an agreed margin, with enough evidence to rule out run-to-run noise;
- cost went over budget;
- latency went over budget.

The gate runs each case several times and compares the two versions case by case, so shared difficulty cancels out.

## Status

Work in progress. Built: two rules on the mean, the naive one (one run per version against a fixed threshold, the default) and a betting rule over all runs that passes, blocks or stays inconclusive and says how many runs a pass would need; the rule on checks over all runs, with critical and minor checks; a comment on every pull or merge request, cost and latency budgets, traces of agent runs, checks over the answer and the trace, any program as a pipeline, and a [dashboard](#dashboard) of the runs. Three projects use the gate, each in its own repository: [receipt-intake](https://github.com/Ilya-Grigoryev/receipt-intake) reads seller, date, address and total from receipt scans for a bookkeeping team (test receipts from [SROIE](https://rrc.cvc.uab.es/?ch=13), ICDAR 2019), from the OCR text or from the scan; [workbench-support](https://github.com/Ilya-Grigoryev/workbench-support) is the support agent of a coworking space, with tools on its booking system and its own test cases, alone on a ticket or in a chat with a simulated user; [telecom-support](https://github.com/Ilya-Grigoryev/telecom-support) is a mobile carrier's support agent built on the telecom domain of [tau2-bench](https://github.com/sierra-research/tau2-bench): tau2's agent, tools, tasks and evaluator, unchanged.

[`docs/design.md`](docs/design.md) describes the parts, the flow of a merge request and the record of a run.

## Your pipeline

Your application answers the gate's cases as a program, in any language. Name it in the config of each version:

```yaml
command: [python, gate/extract.py]  # from where the gate runs: the project's root on a pull request
model: gpt-4.1-mini-2025-04-14      # a dated snapshot if there is one
prompt: prompts/extract.md          # relative to this file, or named files: {extract: a.md, check: b.md}
input: text
params: {temperature: 0}
```

For each run the gate writes one JSON request to the program's stdin: the case's id and input paths and the version's
model, prompt and params, never the expected values. It reads one JSON answer from stdout: `output`, optionally tokens,
the model, the provider's fingerprint and request id, and a trace. Exit 75 retries the run; 78, 126 and 127 stop the
whole run; any other non-zero code fails it. [docs/protocol.md](docs/protocol.md) has every field, the trace steps and
the exit codes; [`protocol.schema.json`](src/llm_release_gate/protocol.schema.json) is the schema the gate checks each
answer against. The site's Get started page shows one program in Python, Node.js and Go
(`dashboard/app/docs/start/page.mdx`); `tests/test_examples.py` runs all three against a fake provider.

`command` is part of the version and its hash, and the program's code is part of the version as any code of the
project is ([Running a version](#running-a-version)).

Prefer a dated snapshot. The gate takes one model name for one model, with or without a date (Anthropic's ids from
Claude 4.6 on are fixed snapshots; other providers' names without a date, such as OpenAI's `gpt-4.1-mini`, may move to a
newer snapshot). For a name without a date every record keeps the requested model next to the one the provider reports,
the gate's comment warns, and the gate refuses to compare two versions that asked for the same model and got different
ones from the provider (or runs that do not say which one they got: report `model`). If the provider moves such a name to
another model, requests get `infra error` until the target branch's cached runs are older than `base_max_age_days`; set
it to `0` on the target branch until then.

The gate imports no application code, only the module of a `function` check. [receipt-intake](https://github.com/Ilya-Grigoryev/receipt-intake) is a whole project set up this way.

## Traces

A tool-using agent makes many calls per case. Its program reports them in the answer's `trace`, a step per model call,
tool call, message or retrieval, with the world's state at the end:

```json
{"output": {"balance": 5},
 "trace": {"steps": [
   {"kind": "llm", "actor": "agent", "status": "ok", "model": "gpt-4.1-mini-2025-04-14",
    "tokens_in": 100, "tokens_out": 10, "cost_usd": null, "tool_calls": [{"id": "c1", "name": "add", "args": {"amount": 5}}]},
   {"kind": "tool", "actor": "agent", "call_id": "c1", "name": "add", "args": {"amount": 5}, "status": "ok",
    "result": {"balance": 5}}],
  "final_state": {"balance": 5}, "state_change": {"balance": 5}, "stop": "done"}}
```

Each step has a kind (`llm`, `tool`, `message`, `retrieval`) and an actor (`agent`, `user`, `system`, `env`);
[docs/protocol.md](docs/protocol.md#trace) lists the fields of each. A model step holds the model the API reported,
tokens, the finish reason and the new output; a tool step holds the name, the arguments, a status and the result or
error. A user simulator's model calls carry `"actor": "user"`, which keeps their cost apart from the agent's. The gate
prices model steps from its price table, so send `cost_usd: null`.

The record gets the trace, tokens and cost per actor (`usage`) and the wall-clock time (`wall_s`). A program that prints
its trace before a failed exit keeps the steps it paid for. A run the runner retries keeps every attempt's steps under
`run_attempt`; checks look at the last attempt, the cost counts all of them. A run stopped by exit 78 is written too when
it paid for steps. `wall_s` includes the runner's backoff between attempts. A program that reports no trace writes
`trace: null`.

## Running a version

Each pipeline version is a YAML file: the program (`command`), model (a dated snapshot if there is one), prompt file (or named prompt files for a pipeline with several steps), input, API parameters and, optionally, `max_retries` (default 5) and `timeout_s` (default 60). Its hash covers every field and the bytes of each prompt; key order, YAML formatting and `0` versus `0.0` do not change it. A version is its config, the bytes of its prompts and the repository's code: every file git tracks, by the id git gives its content (uncommitted edits count; Git LFS, line endings and links read alike in every checkout), but documentation (`README`, `CHANGELOG`, `CONTRIBUTING`, `LICENSE`, bare or as `.md`, `.rst`, `.txt`, `.adoc`, in any case; `docs/`), CI (`.github/`), `gate.yaml` and the price files it names, the paths in its `ignore`, its test sets and the files of its other pipelines (so code that reads another pipeline's prompt does not see it change). A code change gives a new version by itself, in a monorepo a change to shared code or the root lock file too; a change to the README does not. Untracked files (run records, data) do not count, so writing results never changes the version; a run record you commit does. Each record carries the commit too, with `+dirty` for uncommitted edits. A test set that `gate.yaml` does not name is code: name it, or put it in `ignore`.

The runner runs the program K times per case of a golden set and appends one JSON record per call, stamped with the version's hash (`config_hash`), the set hash and the scorer version. A rerun pays only for what is missing. The runner retries rate limits, timeouts and server errors with backoff 1, 2, 4... s and stops when the account is out of quota. `--prices` prices the model steps in each record's `usage`. `<stem>.native.jsonl` is kept for raw provider responses, which nothing records yet.

```sh
# in receipt-intake: the scan version on its golden set, 3 runs per receipt
uv run --env-file .env llm-release-gate run --config configs/sroie-image.yaml --golden data/golden/sroie -k 3 --out runs/image.jsonl
```

## The naive gate

The first gate compares one run per version: it blocks when the candidate's mean score is lower than the base's by more than a threshold, 5 points by default (`--relative` reads it as a percentage of the base mean). It pairs the two files case by case and refuses files with different set hashes, different scorer versions or cases missing from one side. `--golden` rescores both sides from their saved answers with the current scorer, without calling the model.

The rule on checks reads every run: per case and check, Fisher's exact test compares how often the check passed in each version (one-sided, at half of `alpha`, 0.025 by default; Bonferroni over the checks that can reach significance, after Tarone). A check that got significantly worse gives `quality fail` whatever the mean did; `--checks report` (`checks: report` in `gate.yaml`) only lists it. With one run of each version no check can reach significance: at the default `alpha` a single broken check can block from 4 runs of each, several broken at once need more (the correction counts every check that changed or varies), and the comment says when no break can be significant.

`--prices` takes a YAML of `model: [input, output]` in USD per 1M tokens, or `[input, output, cached input]`, and adds what the decision cost: every successful call of both runs. An agent resends the whole dialog on every call, so most of its input is billed as cached; without the third price, cached tokens cost the full input price. For a traced record that means every model step, the user simulator's included.

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
| 11 | inconclusive: the betting rule on the mean could not decide with these runs, or a request removes a pipeline from `gate.yaml` |
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
   llm-release-gate = { git = "https://github.com/Ilya-Grigoryev/llm-release-gate", tag = "v0.1.0-dev.16" }
   ```
2. Write a program that answers one case ([Your pipeline](#your-pipeline)), a config for the version in production and
   a golden set.
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
       permissions: {contents: read, pull-requests: write, actions: read}  # actions: reuse earlier runs
       env:
         OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
       steps:
         - uses: actions/checkout@v7
         - uses: Ilya-Grigoryev/llm-release-gate/setup@v0.1.0-dev.16
         - uses: Ilya-Grigoryev/llm-release-gate@v0.1.0-dev.16
   ```

`gate.yaml` ([`project.schema.json`](src/llm_release_gate/project.schema.json)) takes these fields; settings at the top
apply to every pipeline, and a pipeline's own win:

| Field | Meaning |
|---|---|
| `pipelines.NAME.config`, `.golden` | the version's config and the test set's directory, relative to the project |
| `pipelines.NAME.manifest` | ids and hash the set must match, for a set built or fetched outside git |
| `pipelines.NAME.inputs-url` | where the dashboard finds the set's other files (images): a URL with `{path}` or `{name}` |
| `k` | runs per case and version, default 1; the naive rule reads the first run, the betting rule, the rule on checks and budgets all |
| `delta` | points of mean score the candidate may lose, default 5 |
| `alpha` | the bound on how often the gate blocks a candidate that is no worse, default 0.05, split between the rules; the naive rule has none ([below](#how-often-the-gate-may-be-wrong)) |
| `mean` | `naive` (default): block when the first run's mean drops by more than `delta`; `betting`: pass when the runs show the loss is under `delta`, block when they show it is over, otherwise inconclusive with the number of runs a pass needs (from 2 runs; with δ 5 and 50 cases, a candidate that never differs from the base passes after 2, and noise needs more) |
| `checks` | `block` (default): a check that got significantly worse over the runs blocks; `report`: it is only listed |
| `levels` | `critical: [ids]` block even under `checks: report` and lead the comment; `minor: [ids]` stay out of the case score and only warn (⚠️ in the title, a CI annotation) when significantly worse, as normal checks under `checks: report` do once `levels` is set; `cases: {pattern: level}` for a case's checks, and a `minor` case leaves the mean. Ids take shell patterns (`assert-*`); a pattern that matches no check is named in the comment |
| `prices` | YAML of `model: [input, output]` USD per 1M tokens, for costs and the cost budget |
| `budgets` | `cost_per_run_usd` (needs `prices`), `latency_s` and `latency_quantile` (default 0.95) |
| `base_max_age_days` | the gate reuses the target branch's runs from earlier jobs up to this many days old, default 7; `0` runs both versions in every job |
| `prepare` | a command that readies the project in both trees before their runs, such as `[npm, ci]` |
| `ignore` | glob patterns, from the project's directory, of files that never change what the model gets, such as `web/` (a trailing `/` takes the directory, `**` crosses directories); on top of documentation and CI; `!docs/kb/` takes files back, for an app that reads them |

### How often the gate may be wrong

Under `mean: betting`, `alpha` bounds how often the gate blocks a candidate that is no worse than the base. Each of
the two rules can block on its own, so the gate splits `alpha` between them: half to the betting rule on the mean, half
to the rule on checks. If no check can block (`checks: report` without `critical` levels), the rule on the mean gets
all of it. The betting rule's share bounds a second error: a candidate that lost more than `delta` and passes. Raise
`alpha` to decide sooner, and more such losses pass. The naive rule has no bound of either kind; under `mean: naive`
the rule on checks gets its half and the rest goes unused.

A lower `alpha` means fewer wrong blocks and wrong passes, and more runs before the gate decides. At `delta` 5:

| `alpha` | Each rule's share: false blocks, and missed losses for the betting rule | A check broken in every run can block from | Fully broken checks that can still block at `k: 5` | Runs of each version a pass needs when nothing changed, 10 / 30 / 50 cases |
|---|---|---|---|---|
| 0.01 | 0.005 | `k: 5` | 1 | 14 / 5 / 3 |
| 0.025 | 0.0125 | `k: 5` | 3 | 12 / 4 / 3 |
| 0.05 (default) | 0.025 | `k: 4` | 6 | 10 / 4 / 2 |
| 0.1 | 0.05 | `k: 3` | 12 | 8 / 3 / 2 |

The table assumes checks that may block. With none, the rule on the mean gets all of `alpha`: its runs are in the row
whose share equals your `alpha`, the 0.1 row at the default. The fourth column is a limit of Tarone's correction: when more checks than that break in
every run, it blocks none of them, and the rule on the mean has to catch the break. The comment states the split and
the range's level. If no check could block with the pipeline's `k` and `alpha`, `pr` says so before the runs and names
the `k` or `alpha` that would let it.

`setup` installs Python, uv and the project's locked environment. The gate action first comments that it is running (which also proves it can
comment), checks the golden set (against its manifest, if any), and compares the version from the target branch with the one from the
request, each with its own code; the base runs next to the candidate unless recent runs of it exist (below). A request that leaves a pipeline's version as it is (config,
prompts and code, see [Running a version](#running-a-version)) gets `unchanged` and costs nothing; a pipeline's own
files (another pipeline's prompt, say) do not count for the others. A request that changes `ignore` or which files
belong to which pipeline (the prompts its configs name included) runs every pipeline, so it cannot hide new code from
its own gate. The verdict replaces that note in the same comment, edited again on later pushes.

A version is the same in any commit, so the gate runs it once and shares the runs. Each job uploads the runs it paid
for as an artifact named after the version and the test set (`llm-release-gate-runs-NAME-VERSION-SET`); before running
the base, a later job reuses such runs if they are at most `base_max_age_days` old. A merged request's candidate is the
target branch's new version, so the next request usually finds its base already run, and the comment's cost counts
only what this job paid for. The price: within the age limit, a shift at the provider counts as an effect of the change, and every
request compares with the same base runs, so one noisy base run moves all their verdicts; `base_max_age_days: 0` runs
both versions together, as an experiment that counts the gate's errors should. The gate never reuses runs when the request changes `prepare` or when the target branch has no valid `gate.yaml`. The job needs `actions: read` to find earlier runs;
without it the base runs again and the comment says so.

The rules (`delta`, `alpha`, `k`, `budgets`, `prices`, `base_max_age_days`) come from the target branch's `gate.yaml`, so editing the rules in a
request does not loosen that request's gate: new rules apply after merge, and the comment says when a request changes
them, adds a pipeline or changes a test set. A request that removes a pipeline (or renames it, which looks the same)
fails as inconclusive (exit 11; the other pipelines keep their verdicts): no version of it was compared, so a
maintainer merges it over the check if that is intended. Commit the price file: a file that `prepare` makes is read
after `prepare` has run. The gate matches pipelines by name: a pipeline the target branch's
`gate.yaml` lacks gets `no base version` (the candidate runs alone; its score and budget are reported and the check
passes), and so does every pipeline when the target branch has no `gate.yaml` and no file at the config's path. A new
pipeline follows the target branch's top-level rules; without a `gate.yaml` there, or with a broken one (the comment
warns), the request's rules hold. The gate runs the request's code, its workflow and its lock file, so it catches
mistakes, not a hostile author: protect `.github/`, `gate.yaml` and the lock file with CODEOWNERS for that.

On `pull_request` GitHub gives a request from a fork no secrets, so the gate cannot call the model: the job fails as
`not checked` and says why, and a maintainer gates the request by pushing its branch to the repository. The action
runs on the `pull_request` event; on a push, a manual run or a schedule on the default branch it runs that branch's
version for later requests instead, which is optional. The action keeps
the records as an artifact, and the golden set's case files and text inputs as a second one for 30 days
(`cases: false` leaves it out), so the [dashboard](#dashboard) can show what each case asked. It fails the job with the
gate's verdict; the job only advises until it is made a required check. With several pipelines in `gate.yaml`, add one
step per pipeline with `pipeline: NAME` and `if: ${{ !cancelled() }}` on all but the first, so a block in one does not
skip the others; each gets its own comment and artifact. A golden set that stays out of git is
fetched or built in a step before the gate; if that step fails, the gate does not run and the request gets no comment.

Three private projects use it, each with its own `.github/workflows/ci.yml`: `receipt-intake` (about $0.06 a pull
request), `workbench-support` ($0.14) and `telecom-support` ($0.20).

Outside GitHub Actions the gate's command does the work, from the repository's root. `llm-release-gate pr --base
origin/main --out OUT` runs every pipeline of `gate.yaml` and writes `OUT/NAME` (`--project DIR` when `gate.yaml` is not
at the root, `--list` only checks it; `--cache DIR` reuses the base's runs from a directory the CI keeps between jobs). `llm-release-gate comment OUT/NAME/comment.md --name NAME` posts a verdict (on
GitLab with `GITLAB_TOKEN`, a project access token with the `api` scope); `--running --name NAME` posts that the gate is running and on
how many cases (`--project DIR` as for `pr`), for the verdict to replace; `--check` only tells whether the job can comment, `--dry-run` prints the
comment and posts nothing.

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
