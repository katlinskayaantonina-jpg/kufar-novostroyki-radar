"""Компактная история ранних замеров объявлений для вкладки «Быстрый старт».

Не меняет работу сборщика и его расписание. Каждое объявление хранится независимо
от текущего статуса: снятые остаются в исторических рейтингах.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

WINDOWS = (1, 2, 3, 4, 5, 6, 12, 24)
MAX_GAP = {1: 45, 2: 45, 3: 45, 4: 45, 5: 45, 6: 45, 12: 90, 24: 90}
TZ = timezone(timedelta(hours=3))


def day_key(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d")


def _meta(s: dict, profiles: dict) -> dict:
    pid = str(s.get("pid") or "")
    p = profiles.get(pid) or {}
    keys = ("c", "pid", "cn", "t", "r", "a", "pe", "pu", "ad", "img",
            "nw", "ls", "act", "fv", "fh", "pb4", "rb", "hl", "pp")
    a = {k: s[k] for k in keys if s.get(k) is not None}
    a["seller"] = p.get("name") or s.get("cn") or "Не определён"
    return a


def record_sample(rec: dict, sample: list) -> None:
    """Сохраняем последний фактический замер до конца каждого окна.

    Если до конца окна было более 45/90 мин, измерение помечается неполным,
    без интерполяции и выдуманных просмотров.
    """
    _, ts, v, p = sample
    t = rec["t"]
    if ts < t:
        return
    for hours in WINDOWS:
        deadline = t + hours * 3600
        if ts > deadline:
            continue
        key = str(hours)
        old = rec["w"].get(key)
        if old is None or ts > old[2]:
            rec["w"][key] = [max(0, int(v)), max(0, int(p)), int(ts)]


def build_fast_archive(kv, state: dict, profiles: dict, raw_rows: dict, run_ts: int) -> dict:
    archive = kv.get_json("fast", default=None) or {"v": 1, "ads": {}}
    records = archive.setdefault("ads", {})
    ads = state["ads"]
    earliest = day_key(run_ts - 120 * 86400)
    latest = day_key(run_ts)

    # Первый запуск восстанавливает по сырым измерениям до 120 дней назад.
    # Читаем только даты размещения реально существующих объявлений и следующие сутки.
    backfill = not archive.get("backfilled")
    dates = set()
    for aid, s in ads.items():
        t = int(s.get("lt0") or s.get("fs") or 0)
        if not t:
            continue
        if aid not in records:
            records[aid] = {"t": t, "a": _meta(s, profiles), "w": {}}
        else:
            records[aid]["a"].update(_meta(s, profiles))
        if backfill and earliest <= day_key(t) <= latest:
            dates.add(day_key(t))
            dates.add(day_key(t + 24 * 3600))

    if backfill:
        for day in sorted(d for d in dates if earliest <= d <= latest):
            for row in (kv.get_json("raw:" + day, default=[]) or []):
                aid = str(row[0])
                rec = records.get(aid)
                if rec:
                    record_sample(rec, row)
        archive["backfilled"] = run_ts

    # Добавляем текущие измерения; все ранее зафиксированные старты сохраняются.
    for rows in raw_rows.values():
        for row in rows:
            rec = records.get(str(row[0]))
            if rec:
                record_sample(rec, row)

    # Критерий пригодности вычисляется на клиенте из времени последнего замера.
    # Никогда не подменяем отсутствие измерений нулём просмотров.
    archive["updated"] = run_ts
    kv.put_json("fast", archive)
    return {"ads": len(records), "backfilled_days": len(dates) if backfill else 0}
