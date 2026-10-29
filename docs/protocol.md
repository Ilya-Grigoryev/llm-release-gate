# Pipeline protocol

Version 1. The gate talks to an application in any language through one JSON request and one JSON answer per run.
[`protocol.schema.json`](../src/llm_release_gate/protocol.schema.json) defines both (`$defs`: `request`, `answer`,
`trace`, `step`), and the gate checks every answer against it.

## The program

Name the program in the version's config:

```yaml
pipeline: command
command: [node, agent.js]
model: gpt-5.4-mini-2026-03-17
prompt: prompts/system.md
input: text
```

For each run the gate starts the program in the runner's working directory (relative paths in `command` resolve from
there), writes the request to its stdin and closes it, then reads the answer from its stdout. Write logs to stderr.

```js
// agent.js: answers every case with its id, without a model
let input = "";
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const request = JSON.parse(input);
  process.stdout.write(JSON.stringify({ protocol: 1, output: { id: request.case.id } }));
});
```

[`tests/fixtures/command/agent.sh`](../tests/fixtures/command/agent.sh) is a fuller example in shell, with a trace.

## Request

```json
{"protocol": 1,
 "case": {"id": "synth-001", "inputs": {"text": "/abs/path/synth-001.txt"}},
 "config": {"model": "gpt-5.4-mini-2026-03-17", "prompt": "/abs/path/system.md", "input": "text", "params": {}}}
```

| Field | Meaning |
|---|---|
| `protocol` | the protocol version |
| `case.id` | the case's id |
| `case.inputs` | input name → absolute path of the file |
| `config.model` | the model of the version under test |
| `config.prompt` | absolute path of the prompt, or prompt name → path when the config names several |
| `config.input` | which input the version reads |
| `config.params` | the config's `params`; a whole float arrives as an integer (`1.0` as `1`) |

The program never gets the case's expected values.

## Answer

```json
{"protocol": 1,
 "output": {"total": "12.50"},
 "raw": "{\"total\": \"12.50\"}",
 "input_tokens": 812, "output_tokens": 41,
 "model": "gpt-5.4-mini-2026-03-17",
 "trace": {"steps": [
   {"kind": "llm", "actor": "agent", "status": "ok", "model": "gpt-5.4-mini-2026-03-17",
    "tokens_in": 812, "tokens_out": 41, "cost_usd": null}],
  "final_state": null, "state_change": null, "stop": "done"}}
```

Only `output` is required.

| Field | Meaning |
|---|---|
| `output` | an object the case's checks score, or `null` when there is no answer |
| `raw` | the model's text; any other value is kept as JSON. Default: `output` as JSON |
| `input_tokens`, `output_tokens` | whole numbers ≥ 0, default 0. When the trace has model steps, the gate prices those instead |
| `model` | the model the provider reported. A run with neither `model` nor model steps stays unpriced |
| `trace` | the run's steps and end state, below |
| `protocol` | optional; another version stops the whole run, and the gate keeps none of that answer's trace |

## Trace

`trace` holds `steps`, `final_state` (the world after the run, for state checks), `state_change` and `stop` (why the
run ended: `done`, `max_steps`, `error`…). The gate numbers the steps and replaces any `seq` or `run_attempt` you send.
Each step has a `kind` and an `actor` (`agent`, `user`, `system`, `env`):

| `kind` | Required | Often added |
|---|---|---|
| `llm`, `status: ok` | `model`, `tokens_in`, `tokens_out`, `cost_usd` (`null`: the gate prices the step) | `ts`, `latency_ms`, `tokens_cached`, `tokens_reasoning`, `finish_reason`, `text`, `tool_calls` (`[{id, name, args}]`), `request_id` |
| `llm`, `status: error` | `error`, `attempt` (1 for the first failed try of a call) | `ts`, `latency_ms` |
| `tool` | `status` (`ok`, `error`, `unknown`), `name`, `args` | `call_id`, `result`, `error`, `ts`, `latency_ms` |
| `message` | nothing | `text` |
| `retrieval` | nothing | `docs` (`[{id, …}]`, which the `doc_found` check reads), `query` |

The gate keeps other fields as you send them. A user simulator's calls go under `actor: user`, so their cost stays apart from the
agent's.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | the answer |
| 75 | try again later (rate limit, upstream timeout): the runner backs off and retries |
| 78, 126, 127 | stop the whole run (no quota, wrong key, program not found) |
| any other | this run fails |

The gate keeps a trace the program printed before a failed exit, so paid steps count. An answer that breaks the schema
fails the run, with the path to the field in the error; the steps before a broken step stay.

`timeout_s` in the config bounds the whole program. It runs in its own process group (POSIX only); on timeout the gate
kills the group, loses that attempt's trace and retries. A child that leaves the group (`setsid`, `docker run`) survives
the kill: stop it in the program.

## Versions

`command` is part of the version and its hash, and so is the program's code: the gate hashes the files git tracks in
the project (README, "Running a version").

Within protocol 1 the gate may add request fields and read new optional answer fields: ignore request fields you do
not know. A change that breaks programs gets a new `protocol` number.
