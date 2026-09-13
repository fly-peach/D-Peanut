set -e
B=http://localhost:8010/api
echo "== 1. dataset present =="
curl -s $B/datasets | python3 -c 'import json,sys; d=json.load(sys.stdin); print("datasets:", [(x["name"],x["profile_status"]) for x in d][:4])'
NAME=$(curl -s $B/datasets | python3 -c 'import json,sys; print(next(x["name"] for x in json.load(sys.stdin) if x["kind"]=="file" and x["profile_status"]=="ready"))')
echo "binding dataset: $NAME"

echo "== 2. create asset from bar_topn source =="
SRC=$(python3 -c 'import sys; print(open("/mnt/e/data-agent/backend/tests/fixtures/processors/bar_topn.py").read())')
AID=$(python3 - "$B" "$NAME" "$SRC" <<'PY'
import json, sys, urllib.request
b, name, src = sys.argv[1], sys.argv[2], sys.argv[3]
body = json.dumps({"name": "e2e_topn", "source": src, "chart_type": "bar",
                   "bindings": [{"alias": "sales", "dataset": name}]}).encode()
req = urllib.request.Request(f"{b}/assets", data=body, headers={"Content-Type": "application/json"}, method="POST")
r = json.load(urllib.request.urlopen(req))
print(r["asset"]["id"])
print("status:", r["asset"]["status"], "gate:", r["gate"]["passed"], file=sys.stderr)
PY
)
AID=$(echo "$AID" | tr -d '[:space:]')
echo "created asset id: $AID"

echo "== 3. render present =="
curl -s "$B/assets/$AID/render" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("rows:", d["render"]["row_count"], "gate_passed:", d["gate_passed"], "cols:", d["render"]["tables"]["main"]["dimensions"])'

echo "== 4. break data source (drop revenue col) -> rescan -> replay fails, keeps prior render =="
python3 - "$B" "$AID" "$NAME" <<'PY'
import json, os, sys, urllib.request
b, aid, name = sys.argv[1], sys.argv[2], sys.argv[3]
path = os.environ.get("E2E_CSV", "/home/wt197/data-agent-deploy/data/sales/2021-01.csv")
orig = open(path, encoding="utf-8").read()
broken = "\n".join(l for l in orig.splitlines() if not l.startswith("month,")) # drop header line? no
# safer: rewrite with revenue replaced by a renamed column to trigger KeyError in kernel
lines = orig.splitlines()
hdr = lines[0].split(",")
if "revenue" in hdr:
    i = hdr.index("revenue")
    hdr[i] = "amount"
    lines[0] = ",".join(hdr)
open(path + ".bak", "w", encoding="utf-8").write(orig)
open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
# rescan dataset by name
ds = json.load(urllib.request.urlopen(b + "/datasets"))
row = next(x for x in ds if x["name"] == name)
urllib.request.urlopen(urllib.request.Request(f"{b}/datasets/{row['id']}/rescan", method="POST", data=b""))
import time; time.sleep(2)
r = json.load(urllib.request.urlopen(urllib.request.Request(f"{b}/assets/{aid}/replay", method="POST", data=b"{}")))
print("replay gate passed:", r["gate"]["passed"], "errors:", [e[:80] for e in r["gate"]["errors"]])
os.replace(path + ".bak", path)  # restore original data
PY
echo "prior render still served:"
curl -s "$B/assets/$AID/render" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  cols still:", d["render"]["tables"]["main"]["dimensions"])'

echo "== 5. versioning + history =="
curl -s "$B/assets/$AID/history" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("versions:", d["versions"], "replays:", len(d["replays"]))'

echo "== 6. cleanup =="
curl -s -X DELETE "$B/assets/$AID" -o /dev/null -w "delete http %{http_code}\n"
