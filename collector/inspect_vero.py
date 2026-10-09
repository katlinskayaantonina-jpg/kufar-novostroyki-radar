"""Проверка: откуда у одного сотрудника сотни открытий номера по старым объявлениям. Только агрегаты."""
import json, os, sys, time, traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import requests
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV

DAY = "2026-10-08"
MSK = timezone(timedelta(hours=3))
d0 = datetime.fromisoformat(DAY).replace(tzinfo=MSK).timestamp()
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
     "Accept": "application/json", "Referer": "https://re.kufar.by/"}


def note(t, o):
    s = json.dumps(o, ensure_ascii=False)
    for i in range(0, len(s), 900):
        print(f"::notice title={t}{i//900}::" + s[i:i + 900])


def main():
    kv = KV()
    cat = kv.get_json("catalog", {})
    cube = kv.get_json("cube", {})["days"]
    raw = kv.get_json(f"raw:{DAY}", []) or []
    ads = cat.get("ads", {})
    profs = cat.get("profiles", {})
    pids = {p for p, v in profs.items() if "Хатков" in json.dumps(v, ensure_ascii=False)}
    mine = {a for a, x in ads.items() if x.get("pid") in pids or "Хатков" in str(x.get("cn", ""))}
    D = cube.get(DAY, {})
    old = {a for a in mine if (ads[a].get("lt0") or ads[a].get("lt") or 0) < d0}
    cube_old = [D.get("a", {}).get(a, [0, 0]) for a in old]
    by = defaultdict(list)
    for aid, ts, v, p in raw:
        if aid in old:
            by[aid].append((ts, v, p))
    pos_v = pos_p = net_v = net_p = down_steps = steps = 0
    ads_down = 0
    osc = []
    for a, seq in by.items():
        seq.sort()
        dn = 0
        for (t0, v0, p0), (t1, v1, p1) in zip(seq, seq[1:]):
            steps += 1
            pos_v += max(0, v1 - v0); pos_p += max(0, p1 - p0)
            if v1 < v0 or p1 < p0:
                down_steps += 1; dn += 1
        net_v += max(v for _, v, _ in seq) - seq[0][1]
        net_p += max(p for _, _, p in seq) - seq[0][2]
        if dn:
            ads_down += 1
            if len(osc) < 6:
                osc.append({"p": [p for _, _, p in seq][:24], "v": [v for _, v, _ in seq][:24]})
    out = {"pids": len(pids), "ads_mine": len(mine), "old_ads": len(old),
           "cube_old_dv_dp": [sum(x[0] for x in cube_old), sum(x[1] for x in cube_old)],
           "raw_old_ads_measured": len(by), "steps": steps, "down_steps": down_steps, "ads_with_down": ads_down,
           "sum_positive_dv_dp": [pos_v, pos_p], "net_max_minus_first_dv_dp": [net_v, net_p]}
    note("vero", out)
    note("vero_osc", osc)
    # все объявления за день: насколько сумма плюсов больше реального прироста
    allby = defaultdict(list)
    for aid, ts, v, p in raw:
        allby[aid].append((ts, v, p))
    pv = pp = nv = np_ = dsteps = st = 0
    for seq in allby.values():
        seq.sort()
        for (t0, v0, p0), (t1, v1, p1) in zip(seq, seq[1:]):
            st += 1
            pv += max(0, v1 - v0); pp += max(0, p1 - p0)
            if v1 < v0 or p1 < p0: dsteps += 1
        nv += max(v for _, v, _ in seq) - seq[0][1]
        np_ += max(p for _, _, p in seq) - seq[0][2]
    note("all", {"ads": len(allby), "steps": st, "down_steps": dsteps, "pos_dv_dp": [pv, pp], "net_dv_dp": [nv, np_]})
    # живая проверка: 15 старых объявлений, 8 запросов подряд с паузой 5 сек
    sample = sorted(old)[:15]
    live = []
    for a in sample:
        vals = []
        for _ in range(8):
            try:
                o = requests.get(f"https://statpoints.kufar.by/v1/statpoints/{a}", headers=H, timeout=15).json()
                vals.append((o.get("view"), o.get("phoneview")))
            except Exception:  # noqa: BLE001
                vals.append(None)
            time.sleep(5)
        live.append(vals)
    note("live", {"distinct_values_per_ad": [len(set(v)) for v in live], "examples": live[:4]})


try:
    main()
except Exception:  # noqa: BLE001
    print("::error title=vero::" + traceback.format_exc()[-800:].replace("\n", " | "))
