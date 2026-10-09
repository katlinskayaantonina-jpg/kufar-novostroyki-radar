"""Ряд по дням до/после фильтра робота (Этажи, новостройки). Только агрегаты."""
import json, os, sys, traceback
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV
MSK = timezone(timedelta(hours=3))
try:
    kv = KV(); cat = kv.get_json("catalog", {}); ads = cat["ads"]
    days = kv.get_json("cube", {})["days"]
    comp = {k for k, v in cat.get("companies", {}).items() if "Этаж" in str(v)}
    rows = []
    for d in sorted(days):
        D = days[d]; start = datetime.fromisoformat(d).replace(tzinfo=MSK).timestamp()
        newids = {e[1] for e in D.get("ev", []) if e[2] == "new"}
        r = [d[5:], 0, 0, 0, 0, 0, 0, 0, len(D.get("runs", []))]  # day, adsWithActivity, rawV, rawP, newV, newP, oldV, oldP, runs
        for aid, (v, p) in D.get("a", {}).items():
            a = ads.get(aid)
            if not a or a.get("c") not in comp or not a.get("nw"):
                continue
            r[1] += 1; r[2] += v; r[3] += p
            placed = a.get("lt0") or a.get("fs") or a.get("lt")
            if placed and placed < start and v >= 1 and p >= 1:
                v, p = v - 1, p - 1
            if aid in newids: r[4] += v; r[5] += p
            else: r[6] += v; r[7] += p
        rows.append(r)
    s = json.dumps(rows, ensure_ascii=False)
    for i in range(0, len(s), 900): print(f"::notice title=series{i//900}::" + s[i:i+900])
except Exception:
    print("::error title=x::" + traceback.format_exc()[-800:].replace("\n", " | "))
