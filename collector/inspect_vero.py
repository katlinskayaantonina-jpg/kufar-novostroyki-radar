"""Есть ли «обход» каждый день: доля объявлений с ровно +1 открытием за день. Только агрегаты."""
import json, os, sys, traceback
from collections import Counter
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV
try:
    kv = KV(); cat = kv.get_json("catalog", {}); ads = cat.get("ads", {})
    days = kv.get_json("cube", {})["days"]
    out = {}
    for d in sorted(days)[-14:]:
        A = days[d].get("a", {})
        dp1 = sum(1 for x in A.values() if x[1] == 1)
        out[d] = {"ads": len(A), "dp_total": sum(x[1] for x in A.values()), "ads_dp1": dp1,
                  "ads_dp1_dv1": sum(1 for x in A.values() if x == [1, 1]),
                  "ads_dp_ge2": sum(1 for x in A.values() if x[1] >= 2), "runs": len(days[d].get("runs", []))}
    s = json.dumps(out, ensure_ascii=False)
    for i in range(0, len(s), 900): print(f"::notice title=days{i//900}::" + s[i:i+900])
    # по сырым замерам: в каком интервале прошёл обход (вчера и сегодня)
    for d in ("2026-10-08", "2026-10-09"):
        raw = kv.get_json(f"raw:{d}", []) or []
        seqs = {}
        for aid, ts, v, p in raw: seqs.setdefault(aid, []).append((ts, v, p))
        when = Counter()
        for q in seqs.values():
            q.sort()
            for (t0, v0, p0), (t1, v1, p1) in zip(q, q[1:]):
                if p1 - p0 == 1 and v1 - v0 == 1:
                    when[(t0 // 3600 * 3600 + 3 * 3600) % 86400 // 3600, (t1 + 3 * 3600) % 86400 // 3600] += 1
        print(f"::notice title=when{d}::" + json.dumps(sorted(((f"{a}->{b}", n) for (a, b), n in when.items()), key=lambda x: -x[1])[:15]))
except Exception:
    print("::error title=x::" + traceback.format_exc()[-800:].replace("\n", " | "))
