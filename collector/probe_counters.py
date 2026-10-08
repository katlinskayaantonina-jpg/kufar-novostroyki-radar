"""Эксперимент: меняют ли наши запросы счётчики Kufar. Печатает только агрегаты."""
import json
import os
import random
import sys
import time
import traceback

import requests

sys.path.insert(0, os.path.dirname(__file__))
from kv import KV  # noqa: E402

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
     "Accept": "application/json", "Referer": "https://re.kufar.by/"}


def get(aid):
    for i in range(5):
        try:
            r = requests.get(f"https://statpoints.kufar.by/v1/statpoints/{aid}", headers=H, timeout=15)
            o = r.json() if r.status_code == 200 and r.text.strip() else {}
            return int(o.get("view") or 0), int(o.get("phoneview") or 0)
        except (requests.RequestException, ValueError):
            time.sleep(3 * (i + 1))
    return None


def main():
    st = KV().get_json("state", {})["ads"]
    now = time.time()
    old = [a for a, s in st.items() if s.get("act") and s.get("lt") and now - s["lt"] > 10 * 86400]
    fresh = [a for a, s in st.items() if s.get("act") and s.get("lt") and now - s["lt"] < 6 * 3600]
    random.seed(1)
    sample = {"old": random.sample(old, min(40, len(old))), "fresh": random.sample(fresh, min(20, len(fresh)))}
    res = {}
    for grp, ids in sample.items():
        seq = {a: [] for a in ids}
        for _ in range(6):
            for a in ids:
                seq[a].append(get(a))
            time.sleep(20)
        seq = {a: [x for x in s if x] for a, s in seq.items()}
        seq = {a: s for a, s in seq.items() if len(s) >= 2}
        res[grp] = {
            "ads": len(seq), "requests_per_ad": 6,
            "sum_dv": sum(s[-1][0] - s[0][0] for s in seq.values()),
            "sum_dp": sum(s[-1][1] - s[0][1] for s in seq.values()),
            "steps_v_up": sum(1 for s in seq.values() for x, y in zip(s, s[1:]) if y[0] > x[0]),
            "steps_p_up": sum(1 for s in seq.values() for x, y in zip(s, s[1:]) if y[1] > x[1]),
            "cum_v_mean": round(sum(s[0][0] for s in seq.values()) / max(1, len(seq)), 1),
            "cum_p_mean": round(sum(s[0][1] for s in seq.values()) / max(1, len(seq)), 1),
        }
    print("::notice title=probe::" + json.dumps(res, ensure_ascii=False))


try:
    main()
except Exception:  # noqa: BLE001
    print("::error title=probe::" + traceback.format_exc()[-800:].replace("\n", " | "))
