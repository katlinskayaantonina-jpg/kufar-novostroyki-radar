"""Проверка данных в KV: печатает только агрегаты (без названий и имён)."""
import json, os, re, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV

kv = KV()
st = kv.get_json("state", {}) or {}
cube = kv.get_json("cube", {}) or {}
status = kv.get_json("status", {}) or {}
ads = st.get("ads", {})
act = [s for s in ads.values() if s.get("act")]
out = {
    "ads_total": len(ads), "active": len(act),
    "companies": len(set(s.get("c") for s in act)),
    "with_pid": sum(1 for s in act if s.get("pid")),
    "profiles": len(st.get("profiles", {})),
    "profiles_named": sum(1 for p in st.get("profiles", {}).values() if p.get("name")),
    "newbuild": sum(1 for s in act if s.get("nw")),
    "rooms": dict(Counter(str(s.get("r")) for s in act).most_common(6)),
    "with_img": sum(1 for s in act if s.get("img")),
    "with_addr": sum(1 for s in act if s.get("ad")),
    "measured": sum(1 for s in act if s.get("m")),
    "views_total": sum(s.get("v") or 0 for s in act), "phones_total": sum(s.get("p") or 0 for s in act),
    "poly_pts": len(st.get("polygon") or []),
    "rooms_vs_title": dict(Counter(str(s.get("r")) + "|" + str((re.search(r"(\d)\s*-?\s*(?:комн|к\.|-к)", (s.get("t") or "").lower()) or [None, "?"])[1]) for s in act).most_common(8)),
}
days = cube.get("days", {})
for d in sorted(days)[-3:]:
    D = days[d]
    out[f"day {d}"] = {"ads_with_delta": len(D["a"]), "dv": sum(x[0] for x in D["a"].values()),
                       "dp": sum(x[1] for x in D["a"].values()), "ph_rows": len(D["ph"]), "vh_rows": len(D["vh"]),
                       "events": dict(Counter(e[2] for e in D["ev"])), "cov": D.get("cov"), "runs": len(D.get("runs", []))}
out["last_status"] = {k: status.get(k) for k in ("last_run", "duration_s", "stats")}
items = list(out.items())
chunks, cur = [], {}
for k, v in items:
    cur[k] = v
    if len(json.dumps(cur, ensure_ascii=False)) > 700:
        chunks.append(cur); cur = {}
if cur:
    chunks.append(cur)
for i, c in enumerate(chunks[:9]):
    print(f"::notice title=part{i}::{json.dumps(c, ensure_ascii=False)}")
