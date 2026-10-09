"""Новые объявления одного сотрудника за день + когда ходит робот. Только агрегаты."""
import json, os, sys, traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV

DAY = "2026-10-08"
MSK = timezone(timedelta(hours=3))
d0 = datetime.fromisoformat(DAY).replace(tzinfo=MSK).timestamp()
d1 = d0 + 86400


def note(t, o):
    s = json.dumps(o, ensure_ascii=False)
    for i in range(0, len(s), 900):
        print(f"::notice title={t}{i//900}::" + s[i:i + 900])


def hm(ts):
    return datetime.fromtimestamp(ts, MSK).strftime("%H:%M")


try:
    kv = KV()
    cat = kv.get_json("catalog", {}); ads = cat.get("ads", {}); profs = cat.get("profiles", {})
    cube = kv.get_json("cube", {})["days"]
    raw = (kv.get_json(f"raw:{DAY}", []) or []) + (kv.get_json("raw:2026-10-09", []) or [])
    seqs = defaultdict(list)
    for aid, ts, v, p in raw:
        seqs[aid].append((ts, v, p))
    for q in seqs.values():
        q.sort()
    pids = {p for p, v in profs.items() if "Борискин" in json.dumps(v, ensure_ascii=False)}
    mine = {a for a, x in ads.items() if x.get("pid") in pids}
    newids = {e[1] for e in cube[DAY].get("ev", []) if e[2] == "new"} & mine
    A = cube[DAY].get("a", {})
    tot = [sum(A.get(a, [0, 0])[0] for a in newids), sum(A.get(a, [0, 0])[1] for a in newids)]
    rows = []
    for a in sorted(newids, key=lambda a: -A.get(a, [0, 0])[1]):
        x = ads[a]; q = [r for r in seqs.get(a, []) if r[0] < d1]
        lt = x.get("lt0") or x.get("lt")
        rows.append({"placed": hm(lt) if lt else None, "r": x.get("r"), "a": x.get("a"), "day": A.get(a, [0, 0]),
                     "first": [hm(q[0][0]), q[0][1], q[0][2]] if q else None,
                     "steps": [f"{hm(t1)}:+{v1-v0}/+{p1-p0}" for (t0, v0, p0), (t1, v1, p1) in zip(q, q[1:]) if v1 != v0 or p1 != p0][:14],
                     "end": [q[-1][1], q[-1][2]] if q else None})
    note("bor", {"pids": len(pids), "new_ads": len(newids), "cube_new_dv_dp": tot})
    note("borads", rows[:8])
    # когда ходит робот: по объявлениям, которые замеряются каждый час (интервал <= 80 мин),
    # сколько объявлений получили ровно +1/+1 в каждом часовом интервале и сколько +x/0
    step11 = Counter(); stepv = Counter(); stepp_other = Counter(); measured = Counter()
    for a, q in seqs.items():
        for (t0, v0, p0), (t1, v1, p1) in zip(q, q[1:]):
            if t1 - t0 > 80 * 60:
                continue
            k = datetime.fromtimestamp(t1, MSK).strftime("%d %H")
            measured[k] += 1
            dv, dp = v1 - v0, p1 - p0
            if dv == 1 and dp == 1:
                step11[k] += 1
            elif dp > 0:
                stepp_other[k] += 1
            elif dv > 0:
                stepv[k] += 1
    note("hourly", [[k, measured[k], step11[k], stepp_other[k], stepv[k]] for k in sorted(measured)])
    # ночной интервал (0:xx -> 6:xx) сегодня
    night = Counter()
    for a, q in seqs.items():
        for (t0, v0, p0), (t1, v1, p1) in zip(q, q[1:]):
            if datetime.fromtimestamp(t0, MSK).strftime("%d %H") == "09 00" and datetime.fromtimestamp(t1, MSK).hour == 6:
                night["measured"] += 1
                night[f"{min(v1-v0,3)}/{min(p1-p0,3)}"] += 1
    note("night", dict(night))
except Exception:  # noqa: BLE001
    print("::error title=x::" + traceback.format_exc()[-800:].replace("\n", " | "))
