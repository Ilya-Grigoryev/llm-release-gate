#!/bin/sh
# A pipeline in another language for the gate's tests: reads the request on stdin, answers on stdout.
# `params.mode` in the config picks a behaviour: retry, stop, fail, garbage, slow, badstep; anything else answers.
request=$(cat)
case "$request" in
  *'"mode": "retry"'*) echo "rate limited upstream" >&2; exit 75 ;;
  *'"mode": "stop"'*) echo "no quota left" >&2; exit 78 ;;
  *'"mode": "fail"'*) echo "agent crashed" >&2; exit 3 ;;
  *'"mode": "garbage"'*) echo "not json"; exit 0 ;;
  *'"mode": "slow"'*) sleep 5 ;;
  *'"mode": "badstep"'*) echo '{"output": {}, "trace": {"steps": [{"kind": "llm", "actor": "robot"}]}}'; exit 0 ;;
esac
cat <<'JSON'
{"output": {"company": "TEST MART SDN BHD", "date": "01/01/2026", "address": "1 JALAN UJI, 50000 KUALA LUMPUR",
            "total": "12.50"},
 "raw": "answered by agent.sh", "input_tokens": 12, "output_tokens": 3, "model": "fake-model-2026-01-01",
 "trace": {"steps": [
   {"kind": "llm", "actor": "agent", "status": "ok", "model": "fake-model-2026-01-01", "tokens_in": 12, "tokens_out": 3,
    "cost_usd": null, "tool_calls": [{"id": "c1", "name": "lookup", "args": {"q": "receipt"}}]},
   {"kind": "tool", "actor": "agent", "call_id": "c1", "name": "lookup", "args": {"q": "receipt"}, "status": "ok", "result": 1}],
  "final_state": {"done": true}, "stop": "done"}}
JSON
