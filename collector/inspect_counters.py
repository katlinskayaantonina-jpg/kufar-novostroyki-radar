"""Проверка счётчиков: только агрегаты."""
import json, os, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV
kv = KV()
st = kv.get_json("state", {})["ads"]
raw = kv.get_json("raw:2026-10-08", []) or []
cube = kv.get_json("cube", {})["days"]
by = defaultdict(list)
for aid, ts, v, p in raw:
    by[aid].append((ts, v, p))
out = {"raw_rows": len(raw), "ads": len(by)}
# кумулятивные значения: доля объявлений, где открытий больше чем просмотров
act = [s for s in st.values() if s.get("act") and s.get("v") is not None]
out["cum_p_gt_v"] = sum(1 for s in act if (s.get("p") or 0) > (s.get("v") or 0))
out["cum_ratio_total"] = round(sum(s.get("p") or 0 for s in act) / max(1, sum(s.get("v") or 0 for s in act)), 3)
# приросты между соседними замерами
jumps = Counter(); dvs = []; dps = []; pos_p_zero_v = 0; n = 0
for aid, seq in by.items():
    seq.sort()
    for (t0, v0, p0), (t1, v1, p1) in zip(seq, seq[1:]):
        dv, dp = v1 - v0, p1 - p0
        n += 1
        dvs.append(dv); dps.append(dp)
        if dp > 0 and dv == 0: pos_p_zero_v += 1
        if dp >= 5: jumps["dp>=5"] += 1
        if dp >= 20: jumps["dp>=20"] += 1
        if dp < 0 or dv < 0: jumps["negative"] += 1
out["intervals"] = n
out["sum_dv"], out["sum_dp"] = sum(x for x in dvs if x > 0), sum(x for x in dps if x > 0)
out["dp_pos_with_dv_zero"] = pos_p_zero_v
out["jumps"] = dict(jumps)
out["dp_dist"] = dict(Counter(min(x, 10) for x in dps).most_common(12))
# пример: 5 объявлений с наибольшим приростом открытий за день (без id)
top = sorted(((seq[-1][2] - seq[0][2], seq[-1][1] - seq[0][1], len(seq), seq[0][2], seq[0][1]) for seq in by.values() if len(seq) > 1), reverse=True)[:8]
out["top_dp_dv_n_p0_v0"] = top
# куб за сегодня
D = cube.get("2026-10-08", {})
out["cube_today"] = {"dv": sum(x[0] for x in D.get("a", {}).values()), "dp": sum(x[1] for x in D.get("a", {}).values()), "ads": len(D.get("a", {}))}
# новые объявления сегодня: сколько записано на «с нуля»
new_today = [e[1] for e in D.get("ev", []) if e[2] == "new"]
out["new_today"] = len(new_today)
firsts = [by[a][0] for a in new_today if a in by]
for a in new_today:
    if a in by: by[a].sort()
firsts = [by[a][0] for a in new_today if a in by]
out["new_first_sum_v_p"] = [sum(x[1] for x in firsts), sum(x[2] for x in firsts), len(firsts)]
ids_sorted = sorted(int(a) for a in st)
newids = sorted(int(a) for a in new_today)
out["new_id_rank_pct"] = [round(sum(1 for x in ids_sorted if x < n) / len(ids_sorted), 3) for n in newids[:: max(1, len(newids)//10)]]
big = [a for a in new_today if a in by and by[a][0][1] > 30]
out["new_with_v0_gt30"] = len(big)
out["lt_minus_fs_hours_big"] = sorted(round(((st[a].get("lt0") or 0) - (st[a].get("fs") or 0)) / 3600, 1) for a in big)[:15]
out["new_today_first_counts"] = sorted([(st.get(a, {}).get("p") or 0, st.get(a, {}).get("v") or 0) for a in new_today], reverse=True)[:10]
s = json.dumps(out, ensure_ascii=False)
for i in range(0, len(s), 900):
    print(f"::notice title=c{i//900}::{s[i:i+900]}")
