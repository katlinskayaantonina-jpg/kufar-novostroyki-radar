"""Проверка фильтра робота за 08.10 по двум сотрудникам. Только агрегаты."""
import json, os, sys, traceback
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV
DAY = "2026-10-08"
start = datetime.fromisoformat(DAY).replace(tzinfo=timezone(timedelta(hours=3))).timestamp()
try:
    kv = KV(); cat = kv.get_json("catalog", {}); ads = cat["ads"]; profs = cat["profiles"]
    D = kv.get_json("cube", {})["days"][DAY]
    newids = {e[1] for e in D.get("ev", []) if e[2] == "new"}
    out = {}
    for name in ("Хатков", "Борискин", "Барашенк", "Довгун"):
        pids = {p for p, v in profs.items() if name in json.dumps(v, ensure_ascii=False)}
        r = {"new_v": 0, "new_p": 0, "old_v": 0, "old_p": 0, "bot": 0}
        for aid, (v, p) in D.get("a", {}).items():
            a = ads.get(aid)
            if not a or a.get("pid") not in pids or not a.get("nw"):
                continue
            placed = a.get("lt0") or a.get("fs") or a.get("lt")
            if placed and placed < start and v >= 1 and p >= 1:
                v, p = v - 1, p - 1; r["bot"] += 1
            k = "new" if aid in newids else "old"
            r[k + "_v"] += v; r[k + "_p"] += p
        out[name] = r
    print("::notice title=filtered::" + json.dumps(out, ensure_ascii=False))
except Exception:
    print("::error title=x::" + traceback.format_exc()[-800:].replace("\n", " | "))
