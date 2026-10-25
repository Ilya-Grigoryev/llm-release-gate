#!/bin/sh
# A pipeline in another language for the gate's tests: reads the request on stdin, answers on stdout.
# `params.mode` in the config picks a behaviour (see the cases below); anything else answers.
request=$(cat)
step='{"kind": "llm", "actor": "agent", "status": "ok", "model": "fake-model-2026-01-01", "tokens_in": 12, "tokens_out": 3, "cost_usd": null}'
case "$request" in
  *'"mode": "retry"'*) echo "{\"trace\": {\"steps\": [$step]}}"; echo "rate limited upstream" >&2; exit 75 ;;
  *'"mode": "silentstop"'*) exit 78 ;;
  *'"mode": "stop"'*) echo "{\"trace\": {\"steps\": [$step]}}"; echo "no quota left" >&2; exit 78 ;;
  *'"mode": "fail"'*) echo "{\"trace\": {\"steps\": [$step], \"stop\": \"error\"}}"; echo "agent crashed" >&2; exit 3 ;;
  *'"mode": "failbadtrace"'*) echo '{"trace": {"steps": [{"kind": "llm", "actor": "robot"}]}}'; exit 3 ;;
  *'"mode": "notfound"'*) echo "sh: agent: not found" >&2; exit 127 ;;
  *'"mode": "garbage"'*) echo "not json"; exit 0 ;;
  *'"mode": "slow"'*) sleep 5 ;;
  *'"mode": "badstep"'*) echo '{"output": {}, "trace": {"steps": [{"kind": "llm", "actor": "robot"}]}}'; exit 0 ;;
  *'"mode": "latin1"'*) printf 'caf\351 au lait\n' >&2; printf '{"output": {"note": "caf\351"}}\n'; exit 0 ;;
  *'"mode": "bare"'*) echo '{"output": {"total": "12.50"}}'; exit 0 ;;
  *'"mode": "list"'*) echo '[1, 2]'; exit 0 ;;
  *'"mode": "nooutput"'*) echo '{"raw": "forgot it"}'; exit 0 ;;
  *'"mode": "textoutput"'*) echo '{"output": "12.50"}'; exit 0 ;;
  *'"mode": "nullmodel"'*) echo '{"output": {}, "model": null}'; exit 0 ;;
  *'"mode": "numbermodel"'*) echo '{"output": {}, "model": 4}'; exit 0 ;;
  *'"mode": "rawobject"'*) echo '{"output": {}, "raw": {"text": "hi"}}'; exit 0 ;;
  *'"mode": "negtokens"'*) echo '{"output": {}, "input_tokens": -1}'; exit 0 ;;
  *'"mode": "floattokens"'*) echo '{"output": {}, "output_tokens": 2.5}'; exit 0 ;;
  *'"mode": "badstop"'*) echo '{"output": {}, "trace": {"steps": [], "stop": 3}}'; exit 0 ;;
  *'"mode": "badts"'*) echo '{"output": {}, "trace": {"steps": [{"kind": "message", "actor": "agent", "text": "hi", "ts": 5}]}}'; exit 0 ;;
  *'"mode": "renumber"'*) echo '{"output": {}, "trace": {"steps": [{"kind": "message", "actor": "agent", "text": "hi", "seq": 9, "run_attempt": 4, "self": 1}]}}'; exit 0 ;;
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
