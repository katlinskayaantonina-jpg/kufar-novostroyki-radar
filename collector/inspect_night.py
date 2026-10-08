"""Ночная активность: только агрегаты."""
import json, os, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from kv import KV
kv = KV()
cube = kv.get_json("cube", {})["days"]
st = kv.get_json("state", {})["ads"]
out = {}
# 1) почасовой профиль по старой базе (там замеры шли и ночью)
vh, ph, phads = Counter(), Counter(), defaultdict(set)
days = [d for d in sorted(cube) if "2026-09-23" <= d <= "2026-10-06"]
for d in days:
    D = cube[d]
    for pid, r, h, n in D.get("vh", []):
        if h < 24: vh[h] += n
    for aid, h, n in D.get("ph", []):
        if h < 24: ph[h] += n; phads[h].add(aid)
tv, tp = sum(vh.values()) or 1, sum(ph.values()) or 1
out["days"] = len(days)
out["views_share_by_hour_pct"] = {h: round(100 * vh[h] / tv, 1) for h in range(24)}
out["phones_share_by_hour_pct"] = {h: round(100 * ph[h] / tp, 1) for h in range(24)}
out["phone_per_view_by_hour"] = {h: round(ph[h] / vh[h], 2) if vh[h] else None for h in range(24)}
# 2) прошлая ночь по сырым замерам: последний вечерний -> первый утренний
y = kv.get_json("raw:2026-10-07", []) or []
t = kv.get_json("raw:2026-10-08", []) or []
ev, mo = {}, {}
for aid, ts, v, p in sorted(y, key=lambda r: r[1]): ev[aid] = (ts, v, p)
for aid, ts, v, p in sorted(t, key=lambda r: r[1]):
    if aid not in mo: mo[aid] = (ts, v, p)
pairs = [(a, ev[a], mo[a]) for a in mo if a in ev and 6 * 3600 < mo[a][0] - ev[a][0] < 12 * 3600]
dv = [m[1] - e[1] for a, e, m in pairs]; dp = [m[2] - e[2] for a, e, m in pairs]
old = [i for i, (a, e, m) in enumerate(pairs) if st.get(a, {}).get("lt") and e[0] - st[a]["lt"] > 7 * 86400]
out["night_pairs"] = len(pairs)
out["night_share_ads_view_up_pct"] = round(100 * sum(1 for x in dv if x > 0) / max(1, len(dv)), 1)
out["night_share_ads_phone_up_pct"] = round(100 * sum(1 for x in dp if x > 0) / max(1, len(dp)), 1)
out["night_dv_dist"] = dict(Counter(min(x, 5) for x in dv))
out["night_dp_dist"] = dict(Counter(min(x, 5) for x in dp))
out["night_old_ads"] = len(old)
out["night_old_share_view_up_pct"] = round(100 * sum(1 for i in old if dv[i] > 0) / max(1, len(old)), 1)
out["night_old_share_phone_up_pct"] = round(100 * sum(1 for i in old if dp[i] > 0) / max(1, len(old)), 1)
out["night_phone_without_view"] = sum(1 for i in range(len(dv)) if dp[i] > 0 and dv[i] == 0)
# 3) для сравнения — один дневной час (по кубу за 08.10, точные часы)
D = cube.get("2026-10-08", {})
day_ph = Counter(); day_ads = defaultdict(set)
for aid, h, n in D.get("ph", []):
    if h < 24: day_ph[h] += n; day_ads[h].add(aid)
out["today_phone_ads_by_hour"] = {h: len(day_ads[h]) for h in sorted(day_ads)}
s = json.dumps(out, ensure_ascii=False)
for i in range(0, len(s), 900):
    print(f"::notice title=n{i//900}::{s[i:i+900]}")
