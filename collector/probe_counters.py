"""Эксперимент: меняют ли наши запросы счётчики Kufar. Печатает только агрегаты."""
import json, os, sys, time, random
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV
import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36", "Accept": "application/json", "Referer": "https://re.kufar.by/"}
st = KV().get_json("state", {})["ads"]
now = time.time()
old = [a for a, s in st.items() if s.get("act") and s.get("lt") and now - s["lt"] > 10 * 86400]
fresh = [a for a, s in st.items() if s.get("act") and s.get("lt") and now - s["lt"] < 6 * 3600]
import traceback
try:
    random.seed(1)
    sample = {"old": random.sample(old, min(40, len(old))), "fresh": random.sample(fresh, min(20, len(fresh)))}
    def get(aid):
        r = requests.get(f"https://statpoints.kufar.by/v1/statpoints/{aid}", headers=H, timeout=15)
        o = r.json() if r.status_code == 200 and r.text.strip() else {}
        return int(o.get("view") or 0), int(o.get("phoneview") or 0)
    res = {}
    for grp, ids in sample.items():
        seq = {a: [] for a in ids}
        for rnd in range(6):          # 6 замеров подряд с паузой ~20 сек
            for a in ids:
                seq[a].append(get(a))
            time.sleep(20)
        dv = sum(s[-1][0] - s[0][0] for s in seq.values()); dp = sum(s[-1][1] - s[0][1] for s in seq.values())
        steps_p = sum(1 for s in seq.values() for x, y in zip(s, s[1:]) if y[1] > x[1])
        steps_v = sum(1 for s in seq.values() for x, y in zip(s, s[1:]) if y[0] > x[0])
        res[grp] = {"ads": len(ids), "requests_per_ad": 6, "minutes": 2, "sum_dv": dv, "sum_dp": dp, "steps_with_v_up": steps_v, "steps_with_p_up": steps_p,
                    "cum_v_mean": round(sum(s[0][0] for s in seq.values()) / len(ids), 1), "cum_p_mean": round(sum(s[0][1] for s in seq.values()) / len(ids), 1)}
    print("::notice title=probe::" + json.dumps(res, ensure_ascii=False))

except Exception:
    print("::error title=probe::" + traceback.format_exc()[-800:].replace("\n"," | "))
