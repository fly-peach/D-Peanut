set -e
B=http://localhost:8010/api
echo "===== journey 1: data onboarding ====="
curl -s $B/datasets | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" datasets:", [(x["name"],x["profile_status"]) for x in d])'

echo "===== journey 2: authoring (manual create == write_processor underneath) ====="
NAME=$(curl -s "$B/datasets?kind=file" | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["name"])')
python3 - "$B" "$NAME" <<'PY'
import json, sys, urllib.request
b, name = sys.argv[1], sys.argv[2]
src = open("/mnt/e/data-agent/backend/tests/fixtures/processors/bar_topn.py").read()
body = json.dumps({"name": "mvp_topn", "source": src, "chart_type": "bar",
                   "bindings": [{"alias": "sales", "dataset": name}]}).encode()
r = json.load(urllib.request.urlopen(urllib.request.Request(b + "/assets", data=body,
        headers={"Content-Type": "application/json"}, method="POST")))
print(" create:", r["asset"]["status"], "gate:", r["gate"]["passed"])
open("/tmp/aid", "w").write(r["asset"]["id"])
PY
AID=$(cat /tmp/aid)
curl -s "$B/assets/$AID/render" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" render rows:", d["render"]["row_count"], "dims:", d["render"]["tables"]["main"]["dimensions"])'

echo " -- data params: top_n=2 -> PUT + replay -> v2"
curl -s -X PUT "$B/assets/$AID/params" -H "Content-Type: application/json" \
  -d '{"params":{"top_n":2,"height":320,"show_label":false},"expected_version":1}' -o /dev/null -w "  put: %{http_code}\n"
curl -s -X POST "$B/assets/$AID/replay" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  replay:", d["gate"]["passed"], "v", d["version"], "rows", d["render"]["row_count"])'

echo "===== journey 2b: adhoc -> promote (promote covered by pytest suite) ====="
curl -s "$B/sessions?limit=3" | python3 -c 'import json,sys; print(" sessions listed:", len(json.load(sys.stdin)))'

echo "===== journey 3: runtime determinism + drift + toggle ====="
curl -s -X POST "$B/assets/$AID/replay" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" re-replay stable:", d["gate"]["passed"])'
curl -s -X PUT "$B/settings" -H "Content-Type: application/json" -d '{"settings":{"ai_enabled":false}}' -o /dev/null
SID=$(curl -s -X POST "$B/sessions" -H "Content-Type: application/json" -d '{}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
curl -s -X POST "$B/sessions/$SID/chat" -H "Content-Type: application/json" \
  -d '{"id":"m","trigger":"submit-message","messages":[{"id":"u","role":"user","parts":[{"type":"text","text":"hi"}]}]}' \
  -o /dev/null -w " chat with AI off: %{http_code} (expect 409)\n"
curl -s -X PUT "$B/settings" -H "Content-Type: application/json" -d '{"settings":{"ai_enabled":true}}' -o /dev/null

echo " -- SSE smoke (provider=test):"
curl -s -N --max-time 60 -X POST "$B/sessions/$SID/chat" -H "Content-Type: application/json" \
  -d '{"id":"m","trigger":"submit-message","messages":[{"id":"u","role":"user","parts":[{"type":"text","text":"看看数据"}]}]}' | tail -1 | cut -c1-30
curl -s "$B/sessions/$SID/messages" | python3 -c 'import json,sys; ms=json.load(sys.stdin); print(" restore copies:", len(ms), "roles:", [m["role"] for m in ms])'

echo "===== cleanup ====="
curl -s -X DELETE "$B/assets/$AID" -o /dev/null -w " asset delete: %{http_code}\n"
curl -s -X DELETE "$B/sessions/$SID" -o /dev/null -w " session delete: %{http_code}\n"
echo "===== MVP e2e done ====="
