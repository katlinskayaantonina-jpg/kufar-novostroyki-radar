"""Почему у VIP-объявления не определена дата начала. Только агрегаты."""
import json, os, sys, traceback
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV
M = timezone(timedelta(hours=3)); f = lambda t: datetime.fromtimestamp(t, M).strftime("%d.%m %H:%M") if t else None
try:
    kv = KV(); cat = kv.get_json("catalog", {}); ads = cat["ads"]; days = kv.get_json("cube", {})["days"]
    out = []
    for aid, a in ads.items():
        if not a.get("act") or not (a.get("pp") or a.get("hl")): continue
        pr = [(d[5:], days[d]["pr"][aid]) for d in sorted(days) if aid in days[d].get("pr", {})]
        evs = [(f(e[0]), e[2], e[3], e[4]) for d in sorted(days) for e in days[d].get("ev", []) if e[1] == aid and e[2] in ("promo_pp", "promo_hl", "new")]
        out.append({"addr": (a.get("ad") or "")[:22], "pp": a.get("pp"), "hl": a.get("hl"), "fv": f(a.get("fv")), "fh": f(a.get("fh")), "pb4": a.get("pb4"),
                    "fs": f(a.get("fs")), "lt0": f(a.get("lt0")), "pr": pr[-12:], "ev": evs[-8:]})
    s = json.dumps(out, ensure_ascii=False)
    for i in range(0, len(s), 900): print(f"::notice title=p{i//900:02d}::" + s[i:i+900])
except Exception:
    print("::error title=x::" + traceback.format_exc()[-800:].replace("\n", " | "))
