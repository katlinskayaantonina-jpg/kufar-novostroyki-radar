"""Сборщик: объявления выбранных агентств в выбранном районе Kufar.

Один запуск:
  1. скачивает выдачу района (все страницы) и ленты известных профилей продавцов;
  2. отбирает объявления нужных компаний внутри района;
  3. фиксирует события (новое, снято, поднятие, цена, продвижение, заголовок, фото);
  4. снимает счётчики просмотров и открытий номера: свежие объявления — каждый запуск,
     остальные — по очереди, примерно раз в 6 часов;
  5. раскладывает прирост по часам и сохраняет всё в Cloudflare KV.

Только чтение (GET). В журнал печатаются только количества.
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import os
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kv import KV  # noqa: E402
import geo  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=3))  # Минск, без перехода на летнее время

SEARCH_API = "https://cre-api.kufar.by/ads-search/v1/engine/v1/search/rendered-paginated"
STAT_API = "https://statpoints.kufar.by/v1/statpoints/"
DISTRICT_CODE = "170"
COMPLEX_CODE = "315"
DISTRICT_PARAMS = {"rgn": "7", "cat": "1010", "typ": "sell", "red": DISTRICT_CODE, "sort": "lst.d"}

HOT_LIST_DAYS = 7          # поднятые/размещённые за 7 дней — замер каждый запуск
HOT_FIRST_SEEN_DAYS = 2
COLD_EVERY_HOURS = 6
COLD_CAP = 1800
COUNTER_WORKERS = 6
EXACT_MAX_MIN = 80         # интервал до 80 минут — приписываем конкретному часу
NIGHT_BUCKET = 24          # ночь между последним вечерним и первым утренним замером
SPREAD_BUCKET = 25         # длинный интервал днём — час неизвестен
RESOLVE_CAP = 40           # сколько неизвестных продавцов уточнять за запуск
CUBE_DAYS = 92
RAW_TTL_DAYS = 120
ADS_KEEP_DAYS = 100

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "application/json,text/plain,*/*",
    "Origin": "https://www.kufar.by",
    "Referer": "https://www.kufar.by/",
}

STATS = Counter()


def log(msg: str) -> None:
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


def now_ts() -> int:
    return int(time.time())


def local(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, TZ)


def day_key(ts: float) -> str:
    return local(ts).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- конфиг
def load_private_config() -> dict:
    """Список компаний и профилей. Хранится зашифрованным (config/private.enc) или, временно, открытым."""
    enc = ROOT / "config" / "private.enc"
    plain = ROOT / "config" / "private.json"
    key = os.environ.get("RADAR_KEY", "").strip()
    if enc.exists() and key:
        from crypto import decrypt  # noqa: E402
        return json.loads(decrypt(enc.read_bytes(), key).decode("utf-8"))
    if plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    raise RuntimeError("Нет конфигурации компаний (config/private.enc + RADAR_KEY)")


# ---------------------------------------------------------------- HTTP
def http_get(url: str, *, params=None, headers=None, timeout=(8, 45), attempts=5, allow_redirects=True):
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers or H, timeout=timeout, allow_redirects=allow_redirects)
            if r.status_code in (408, 425, 429, 500, 502, 503, 504):
                STATS[f"http_{r.status_code}"] += 1
                ra = r.headers.get("Retry-After")
                delay = float(ra) if ra and ra.isdigit() else (2, 5, 10, 20, 30)[i]
                time.sleep(min(delay, 60))
                last = r
                continue
            return r
        except requests.RequestException as e:
            STATS["net_retry"] += 1
            last = e
            time.sleep((2, 5, 10, 20, 30)[i])
    if isinstance(last, requests.Response):
        return last
    raise last  # type: ignore[misc]


def next_token(data: dict) -> str:
    for p in (data.get("pagination") or {}).get("pages") or []:
        if isinstance(p, dict) and p.get("label") == "next" and p.get("token"):
            return str(p["token"])
    return ""


def crawl(params: dict, max_pages: int = 120, stop=None) -> tuple[list[dict], bool]:
    """Все страницы выдачи. stop(ads_on_page) -> True прерывает. Возвращает (объявления, дошли_до_конца)."""
    out, cursor, pages, seen = [], "", 0, set()
    while pages < max_pages:
        p = dict(params, size="200", lang="ru")
        if cursor:
            p["cursor"] = cursor
        r = http_get(SEARCH_API, params=p)
        for wait in (20, 60):
            if r.status_code != 403:
                break
            STATS["search_403"] += 1
            time.sleep(wait)
            r = http_get(SEARCH_API, params=p)
        if r.status_code != 200:
            raise RuntimeError(f"search HTTP {r.status_code}")
        data = r.json()
        ads = data.get("ads") or []
        out.extend(ads)
        pages += 1
        STATS["search_pages"] += 1
        cursor = next_token(data)
        if not cursor or not ads:
            return out, True
        if cursor in seen:
            return out, False
        seen.add(cursor)
        if stop and stop(ads):
            return out, False
        time.sleep(0.25)
    return out, False


# ---------------------------------------------------------------- разбор объявления
def pe(arr) -> dict:
    return {str(x.get("p")): x for x in (arr or []) if isinstance(x, dict) and x.get("p") is not None}


def _v(m: dict, k: str):
    return (m.get(k) or {}).get("v")


def _vl(m: dict, k: str) -> str:
    v = (m.get(k) or {}).get("vl")
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v if x)
    return str(v or "")


def _num(x, scale=1.0):
    try:
        return round(float(x) / scale, 2)
    except (TypeError, ValueError):
        return None


def iso_to_ts(s: str) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def parse_ad(ad: dict) -> dict:
    acc = pe(ad.get("account_parameters"))
    ap = pe(ad.get("ad_parameters"))
    ps = ad.get("paid_services") or {}
    coords = _v(ap, "coordinates")
    lat = lon = None
    if isinstance(coords, list) and len(coords) >= 2:
        lon, lat = _num(coords[0]), _num(coords[1])  # Kufar отдаёт [долгота, широта]
    img = ""
    for im in ad.get("images") or []:
        if isinstance(im, dict) and im.get("path"):
            img = "https://rms.kufar.by/v1/gallery/" + str(im["path"]).lstrip("/")
            break
    rooms = _v(ap, "rooms")
    cond = _vl(ap, "condition")
    return {
        "id": str(ad.get("ad_id") or ad.get("list_id") or ""),
        "unp": str(_v(acc, "vat_number") or ""),
        "cn": str(_v(acc, "contact_person") or "").strip(),
        "acc": str(ad.get("account_id") or ""),
        "t": str(ad.get("subject") or "").strip(),
        "r": str(rooms) if rooms not in (None, "") else "",
        "a": _num(_v(ap, "size")),
        "fl": str(_v(ap, "floor") or ""),
        "ft": str(_v(ap, "re_number_floors") or ""),
        "pu": _num(ad.get("price_usd"), 100.0),
        "pb": _num(ad.get("price_byn"), 100.0),
        "cur": "USD" if str(ad.get("currency") or "").upper() == "USD" else "BYN",
        "ad": str(_v(acc, "address") or "").strip() or _vl(ap, "address"),
        "lt": iso_to_ts(ad.get("list_time")),
        "img": img,
        "ni": len(ad.get("images") or []),
        "hl": 1 if ps.get("highlight") else 0,
        "pp": 1 if ps.get("polepos") else 0,
        "rb": json.dumps(ps.get("ribbons"), ensure_ascii=False, sort_keys=True) if ps.get("ribbons") else "",
        "nw": 1 if (_v(ap, "flat_new_building") is True or cond.lower().startswith("нов")) else 0,
        "cond": cond,
        "dist": str(_v(ap, "re_district") or ""),
        "cx": str(_v(ap, "new_buildings_apartment_complex") or ""),
        "lat": lat,
        "lon": lon,
    }


# ---------------------------------------------------------------- профили продавцов
PROFILE_RE = re.compile(r"https?://(?:re|www)\.kufar\.by/p/[^\"'<> \\]+|[\"']([^\"']*/p/[^\"']+)[\"']")


def resolve_profile(ad_id: str) -> str | None:
    """Номер профиля продавца со страницы объявления (ссылка вида /p/.../12345)."""
    try:
        r = requests.get(f"https://re.kufar.by/vi/{ad_id}", headers={**H, "Accept": "text/html,*/*"},
                         timeout=(6, 25), allow_redirects=True)
    except requests.RequestException:
        STATS["resolve_err"] += 1
        return None
    if r.status_code == 429:
        STATS["resolve_429"] += 1
        return "RATE"
    if r.status_code != 200:
        STATS["resolve_http"] += 1
        return None
    body = r.text.replace("\\/", "/")
    for m in PROFILE_RE.finditer(body):
        href = html.unescape(m.group(1) or m.group(0))
        tail = href.split("?")[0].rstrip("/").split("/")[-1]
        if re.fullmatch(r"\d{3,20}", tail):
            return tail
    STATS["resolve_none"] += 1
    return None


# ---------------------------------------------------------------- счётчики
def read_counter(ad_id: str) -> tuple[str, int | None, int | None, int]:
    url = STAT_API + ad_id
    if "increment" in url.lower() or not re.fullmatch(r"\d{5,20}", ad_id):
        return ad_id, None, None, now_ts()
    try:
        r = http_get(url, headers={"User-Agent": H["User-Agent"], "Accept": "application/json", "Referer": "https://re.kufar.by/"},
                     timeout=(5, 15), attempts=3, allow_redirects=False)
        ts = now_ts()
        if r.status_code != 200:
            STATS["counter_http_err"] += 1
            return ad_id, None, None, ts
        obj = r.json() if r.text.strip() else {}
        if not isinstance(obj, dict):
            return ad_id, None, None, ts
        return ad_id, int(obj.get("view") or 0), int(obj.get("phoneview") or 0), ts
    except Exception:  # noqa: BLE001
        STATS["counter_err"] += 1
        return ad_id, None, None, now_ts()


def bucket_for(t0: int, t1: int) -> tuple[str, int]:
    """(дата, час) для прироста между замерами t0 и t1."""
    span_min = (t1 - t0) / 60
    if span_min <= EXACT_MAX_MIN:
        mid = local((t0 + t1) / 2)
        return mid.strftime("%Y-%m-%d"), mid.hour
    a, b = local(t0), local(t1)
    if a.date() != b.date() or a.hour >= 22 or b.hour <= 8:
        # перерыв на ночь: последний вечерний замер -> первый утренний
        if (b - a) <= timedelta(hours=14) and (a.hour >= 20 or b.hour <= 9):
            return b.strftime("%Y-%m-%d"), NIGHT_BUCKET
    return b.strftime("%Y-%m-%d"), SPREAD_BUCKET


# ---------------------------------------------------------------- основной запуск
def merge_import(state: dict, cube: dict) -> str:
    """Однократное подмешивание истории со старой базы (import/radar_import.json.gz)."""
    path = ROOT / "import" / "radar_import.json.gz"
    if not path.exists():
        return ""
    import gzip as _gz
    data = json.loads(_gz.decompress(path.read_bytes()).decode("utf-8"))
    sig = str(data.get("generated"))
    if state.get("imported") == sig:
        return "already"
    days = cube.setdefault("days", {})
    replaced = 0
    for d, D in (data.get("days") or {}).items():
        live = days.get(d)
        if live is None or len(live.get("runs") or []) < 3:
            if live:  # оставить свои события того дня
                D["ev"] = (D.get("ev") or []) + [e for e in live.get("ev") or [] if e[2] in ("new", "gone", "back")]
                D["runs"] = live.get("runs") or []
            days[d] = D
            replaced += 1
    added = 0
    ads = state["ads"]
    for aid, a in (data.get("ads") or {}).items():
        s = ads.get(aid)
        if s is None:
            ads[aid] = dict(a, act=0, m=0)
            added += 1
            continue
        for k in ("lt0", "fs"):
            if a.get(k) and (not s.get(k) or a[k] < s[k]):
                s[k] = a[k]
        for k in ("pid", "cn"):
            if a.get(k) and not s.get(k):
                s[k] = a[k]
    state["imported"] = sig
    return f"days={replaced} ads_added={added}"


def rebuild_day(kv, cube: dict, dkey: str, ads_state: dict) -> str:
    """Пересчёт приростов за день по сырым замерам (однократное исправление)."""
    rows = kv.get_json(f"raw:{dkey}", default=[]) or []
    prev_day = (datetime.fromisoformat(dkey) - timedelta(days=1)).strftime("%Y-%m-%d")
    before = kv.get_json(f"raw:{prev_day}", default=[]) or []
    last: dict = {}
    for aid, ts, v, p in sorted(before, key=lambda r: r[1]):
        last[aid] = (ts, v, p)
    known_before = set(last)
    max_before = max([0] + [int(a) for a in known_before])
    d = cube["days"].setdefault(dkey, empty_day())
    a_tot: dict = {}
    vh: Counter = Counter()
    ph: Counter = Counter()
    cov: Counter = Counter()
    for aid, ts, v, p in sorted(rows, key=lambda r: r[1]):
        s = ads_state.get(aid, {})
        pr = last.get(aid)
        if pr is None and int(aid) > max_before and s.get("lt0") and s.get("lt0") == s.get("lt") and ts - s["lt0"] < 3 * 3600:
            pr = (s["lt0"], 0, 0)
        last[aid] = (ts, v, p)
        if pr is None:
            continue
        dv, dp = max(0, v - pr[1]), max(0, p - pr[2])
        dk, h = bucket_for(pr[0], ts)
        if dk != dkey:
            continue
        cov[str(h)] += 1
        if dv or dp:
            x = a_tot.setdefault(aid, [0, 0])
            x[0] += dv
            x[1] += dp
            if dv:
                vh[(s.get("pid") or "", s.get("r") or "", h)] += dv
            if dp:
                ph[(aid, h)] += dp
    old = (sum(x[0] for x in d["a"].values()), sum(x[1] for x in d["a"].values()))
    d["a"] = a_tot
    d["vh"] = [[k[0], k[1], k[2], n] for k, n in vh.items()]
    d["ph"] = [[k[0], k[1], n] for k, n in ph.items()]
    d["cov"] = dict(cov)
    new = (sum(x[0] for x in a_tot.values()), sum(x[1] for x in a_tot.values()))
    return f"{dkey}: views {old[0]}->{new[0]}, phones {old[1]}->{new[1]}"


def merge_promo_history(state: dict, cube: dict) -> str:
    """Однократно: история рекламы (VIP/выделение) из Kufar Promo Intelligence, зашифрована RADAR_KEY."""
    path = ROOT / "import" / "promo_history.enc"
    key = os.environ.get("RADAR_KEY", "").strip()
    if not path.exists() or not key:
        return ""
    from crypto import decrypt  # noqa: E402
    data = json.loads(decrypt(path.read_bytes(), key).decode("utf-8"))
    sig = str(data.get("generated"))
    if state.get("promo_imported") == sig:
        return ""
    days = cube.setdefault("days", {})
    for d, D in (data.get("days") or {}).items():
        day = days.setdefault(d, empty_day())
        pr = day.setdefault("pr", {})
        for aid, code in D.get("pr", {}).items():
            pr[aid] = max(pr.get(aid, 0), code)
        pe = day.setdefault("pe", {})
        for aid, by in D.get("pe", {}).items():
            for k, (dv, dp) in by.items():
                cur = pe.setdefault(aid, {}).setdefault(k, [0, 0])
                cur[0] += dv
                cur[1] += dp
    n = 0
    for aid, a in (data.get("ads") or {}).items():
        s = state["ads"].get(aid)
        if s is None:
            continue
        n += 1
        for k in ("fv", "fh"):
            if a.get(k):
                s[k] = min(s.get(k) or a[k], a[k])
        if a.get("pb4"):
            s["pb4"] = 1
    state["promo_imported"] = sig
    return f"days={len(data.get('days') or {})} ads={n}"


def empty_day() -> dict:
    return {"a": {}, "ph": [], "vh": [], "ev": [], "cov": {}, "runs": []}


def main() -> int:
    t_start = time.time()
    run_ts = now_ts()
    cfg = load_private_config()
    companies = cfg["companies"]
    unp_to_company = {u: ck for ck, c in companies.items() for u in c["unp"]}

    kv = KV()
    state = kv.get_json("state", default=None) or {"v": 1, "ads": {}, "profiles": {}, "last_run": 0,
                                                    "last_full_feeds": 0, "tries": {}}
    bootstrap = not state["ads"]
    prev_max_id = int(state.get("max_id") or max([0] + [int(a) for a in state["ads"] if a.isdigit()]))
    ads_state: dict = state["ads"]
    profiles: dict = state["profiles"]
    for pid, p in (cfg.get("profiles") or {}).items():
        cur = profiles.setdefault(pid, {})
        cur["company"] = p.get("company") or cur.get("company")
        if p.get("name"):
            cur["name"] = p["name"]
            cur["auto"] = 0

    # --- граница района
    kml_polys = geo.load_kml_polygons(ROOT / "config" / "district.kml")

    # --- 1. выдача района
    log("Шаг 1: выдача района")
    try:
        district_raw, district_complete = crawl(DISTRICT_PARAMS, max_pages=150)
    except Exception as e:  # noqa: BLE001
        # Kufar временно не отдаёт выдачу этому серверу: счётчики всё равно снимем
        STATS["district_error"] = str(e)[:80]  # type: ignore[assignment]
        district_raw, district_complete = [], False
    STATS["district_ads"] = len(district_raw)
    parsed: dict[str, dict] = {}
    district_ids = set()
    pts = []
    for a in district_raw:
        r = parse_ad(a)
        if not r["id"]:
            continue
        district_ids.add(r["id"])
        if r["lat"] is not None:
            pts.append((r["lat"], r["lon"]))
        if r["unp"] in unp_to_company:
            parsed[r["id"]] = r
    hull = geo.hull_from_district_points(pts) if not kml_polys else []
    polys = kml_polys or ([hull] if hull else [])
    if polys:
        state["polygon_source"] = "kml" if kml_polys else "hull"

    def in_district(r: dict) -> bool:
        if r["dist"] == DISTRICT_CODE or r["cx"] == COMPLEX_CODE:
            return True
        if r["lat"] is not None and polys:
            return any(geo.inside(r["lat"], r["lon"], p) for p in polys)
        return False

    # --- 2. ленты профилей (дают номер профиля продавца и объявления вне отметки района)
    log("Шаг 2: ленты профилей")
    full_feeds = bootstrap or (run_ts - int(state.get("last_full_feeds") or 0) > 20 * 3600)
    feed_seen: set[str] = set()
    ad_profile: dict[str, str] = {}
    feed_ok = True
    for pid, p in sorted(profiles.items()):
        if p.get("company") not in companies:
            continue
        cutoff = int(state.get("last_run") or 0) - 3 * 3600

        def stop(page_ads, cutoff=cutoff):
            if full_feeds:
                return False
            # лента отсортирована по дате размещения: дальше только то, что видели в прошлых запусках
            lts = [iso_to_ts(x.get("list_time")) or 0 for x in page_ads]
            return bool(lts) and max(lts) < cutoff

        try:
            feed, _ = crawl({"atid": pid, "typ": "sell", "prn": "1000", "sort": "lst.d"}, max_pages=120, stop=stop)
        except Exception:  # noqa: BLE001
            feed_ok = False
            STATS["feed_err"] += 1
            continue
        STATS["feed_ads"] += len(feed)
        for a in feed:
            r = parse_ad(a)
            if not r["id"]:
                continue
            feed_seen.add(r["id"])
            ad_profile[r["id"]] = pid
            if r["unp"] in unp_to_company and r["id"] not in parsed and in_district(r):
                parsed[r["id"]] = r
    if full_feeds and feed_ok:
        state["last_full_feeds"] = run_ts

    # --- 2b. дополнительные запросы (для компаний без профилей сотрудников)
    for q in cfg.get("extra_queries") or []:
        try:
            extra, _ = crawl(dict(q, sort="lst.d"), max_pages=10)
        except Exception:  # noqa: BLE001
            STATS["extra_err"] += 1
            continue
        for a in extra:
            r = parse_ad(a)
            if r["id"] and r["unp"] in unp_to_company and r["id"] not in parsed and in_district(r):
                parsed[r["id"]] = r

    # отбор: только нужные компании внутри района
    current = {aid: r for aid, r in parsed.items() if in_district(r)}
    STATS["competitor_ads_now"] = len(current)
    log(f"Объявлений конкурентов в районе сейчас: {len(current)}")

    # --- 3. события
    log("Шаг 3: события")
    events: list[list] = []

    def ev(aid, kind, old="", new=""):
        events.append([run_ts, aid, kind, old, new])

    for aid, r in current.items():
        s = ads_state.get(aid)
        company = unp_to_company[r["unp"]]
        pid = ad_profile.get(aid) or (s or {}).get("pid") or ""
        if s is None:
            s = ads_state[aid] = {"fs": run_ts, "lt0": r["lt"], "v": None, "p": None, "m": 0, "lp": 0}
            if not bootstrap:
                ev(aid, "new", "", r["lt"] or "")
        else:
            if not s.get("act"):
                ev(aid, "back")
            if r["lt"] and s.get("lt") and r["lt"] - s["lt"] > 600:
                ev(aid, "raise", s["lt"], r["lt"])
            # сравниваем цену в валюте объявления: долларовая цена BYN-объявлений меняется с курсом
            po_new = r["pu"] if r["cur"] == "USD" else r["pb"]
            po_old = s.get("pu") if r["cur"] == "USD" else s.get("pb")
            if po_new and po_old and s.get("cur", r["cur"]) == r["cur"] and abs(po_new - po_old) >= max(1, po_old * 0.002):
                ev(aid, "price", s.get("pu") or "", r["pu"] or "")
            for k, name in (("hl", "promo_hl"), ("pp", "promo_pp"), ("rb", "promo_rb")):
                if (s.get(k) or 0) != (r[k] or 0) and not (not s.get(k) and not r[k]):
                    ev(aid, name, s.get(k) or "", r[k] or "")
            if s.get("t") and s["t"] != r["t"]:
                ev(aid, "title", s["t"], r["t"])
            if s.get("img") and s["img"] != r["img"]:
                ev(aid, "photo")
        s.update({k: r[k] for k in ("t", "r", "a", "fl", "ft", "pu", "pb", "cur", "ad", "lt", "img", "ni", "hl", "pp", "rb",
                                     "nw", "cond", "dist", "lat", "lon", "cn")})
        s["c"] = company
        if r["pp"]:
            s["fv"] = min(s.get("fv") or run_ts, run_ts)
        if r["hl"]:
            s["fh"] = min(s.get("fh") or run_ts, run_ts)
        s["pid"] = pid
        s["ls"] = run_ts
        s["act"] = 1
        s.pop("miss", None)
        if pid and pid not in profiles:
            profiles[pid] = {"company": company, "name": "", "auto": 1}

    # снятые объявления: только если выдача района прошла целиком
    if district_complete:
        for aid, s in ads_state.items():
            if not s.get("act") or aid in current:
                continue
            in_district_mark = s.get("dist") == DISTRICT_CODE
            if in_district_mark or (full_feeds and feed_ok and aid not in feed_seen):
                # постраничная выдача иногда «теряет» объявление на один обход — ждём два подряд
                s["miss"] = int(s.get("miss") or 0) + 1
                if s["miss"] >= 2:
                    s["act"] = 0
                    ev(aid, "gone")
    STATS["events"] = len(events)

    # --- 4. уточнение продавцов для объявлений без профиля
    tries = state.setdefault("tries", {})
    unresolved = [aid for aid, s in ads_state.items() if s.get("act") and not s.get("pid") and tries.get(aid, 0) < 3]
    STATS["unresolved_before"] = len(unresolved)
    unresolved.sort(key=lambda a: (tries.get(a, 0), -(ads_state[a].get("fs") or 0)))
    resolved_now = 0
    for aid in unresolved[:RESOLVE_CAP]:
        res = resolve_profile(aid)
        if res == "RATE":
            break
        tries[aid] = tries.get(aid, 0) + 1
        if res:
            s = ads_state[aid]
            s["pid"] = res
            resolved_now += 1
            if res not in profiles:
                profiles[res] = {"company": s.get("c"), "name": "", "auto": 1}
        time.sleep(2.0)
    STATS["resolved_now"] = resolved_now

    # автоматические имена для профилей без имени: самое частое контактное имя
    names: dict[str, Counter] = defaultdict(Counter)
    for s in ads_state.values():
        if s.get("pid") and s.get("cn"):
            names[s["pid"]][s["cn"]] += 1
    for pid, p in profiles.items():
        if (not p.get("name") or p.get("auto")) and names.get(pid):
            p["name"] = names[pid].most_common(1)[0][0]
            p["auto"] = 1

    # --- 5. счётчики
    log("Шаг 4: счётчики просмотров и открытий номера")
    hot, cold = [], []
    for aid, s in ads_state.items():
        if not s.get("act"):
            continue
        is_hot = (
            (s.get("lt") and run_ts - s["lt"] < HOT_LIST_DAYS * 86400)
            or (s.get("lt0") and run_ts - s["lt0"] < HOT_FIRST_SEEN_DAYS * 86400)
            or s.get("hl") or s.get("pp") or s.get("rb")
            or not s.get("m")
        )
        if is_hot:
            hot.append(aid)
        elif run_ts - (s.get("m") or 0) >= COLD_EVERY_HOURS * 3600:
            cold.append(aid)
    cold.sort(key=lambda a: ads_state[a].get("m") or 0)
    cold = cold[:COLD_CAP]
    to_measure = hot + cold
    STATS["measure_hot"], STATS["measure_cold"] = len(hot), len(cold)

    results = []
    with cf.ThreadPoolExecutor(COUNTER_WORKERS) as ex:
        for res in ex.map(read_counter, to_measure):
            results.append(res)
    STATS["measured_ok"] = sum(1 for r in results if r[1] is not None)

    cube = kv.get_json("cube", default=None) or {"days": {}}
    if not state.get("fix_baseline_0810"):
        STATS["rebuilt_day"] = rebuild_day(kv, cube, "2026-10-08", ads_state)  # type: ignore[assignment]
        state["fix_baseline_0810"] = 1
    if not state.get("fix_price_0810"):
        d0 = cube["days"].get("2026-10-08")
        if d0:
            before = len(d0["ev"])
            d0["ev"] = [e for e in d0["ev"] if e[2] != "price"]
            STATS["fixed_price_events"] = before - len(d0["ev"])
        state["fix_price_0810"] = 1
    pimp = merge_promo_history(state, cube)
    if pimp:
        STATS["promo_import"] = pimp  # type: ignore[assignment]
    imp = merge_import(state, cube)
    if imp and imp != "already":
        STATS["import"] = imp  # type: ignore[assignment]
    days = cube["days"]
    raw_rows: dict[str, list] = defaultdict(list)
    adds_a: dict[str, dict[str, list]] = defaultdict(dict)
    adds_vh: dict[str, Counter] = defaultdict(Counter)
    adds_ph: dict[str, Counter] = defaultdict(Counter)
    cov: dict[str, Counter] = defaultdict(Counter)
    adds_pe: dict[str, dict] = defaultdict(dict)

    for aid, v, p, ts in results:
        if v is None:
            continue
        s = ads_state[aid]
        raw_rows[day_key(ts)].append([aid, ts, v, p])
        prev_v, prev_p, prev_m = s.get("v"), s.get("p"), s.get("m") or 0
        if (prev_m == 0 and not bootstrap and s.get("fs") == run_ts and s.get("lt") and ts - s["lt"] < 3 * 3600
                and int(aid) > prev_max_id and s.get("lt0") == s.get("lt")):
            # действительно новое объявление (номер больше всех, что мы видели раньше):
            # считаем от нуля с момента размещения. Старые объявления, впервые попавшие в радар, так не считаем.
            prev_v, prev_p, prev_m = 0, 0, s["lt"]
        if prev_m and prev_v is not None:
            dv = v - prev_v
            dp = p - (prev_p or 0)
            if dv < 0 or dp < 0:
                STATS["counter_went_down"] += 1
                dv, dp = max(dv, 0), max(dp, 0)
            dkey, hour = bucket_for(prev_m, ts)
            cov[dkey][str(hour)] += 1
            promo = 2 if s.get("pp") else 1 if s.get("hl") else 0
            if promo and (dv or dp) and s.get("ls") == run_ts:
                pe = adds_pe[day_key(ts)].setdefault(aid, {}).setdefault(str(promo), [0, 0])
                pe[0] += dv
                pe[1] += dp
            if dv or dp:
                cur = adds_a[dkey].setdefault(aid, [0, 0])
                cur[0] += dv
                cur[1] += dp
                if dv:
                    adds_vh[dkey][(s.get("pid") or "", s.get("r") or "", hour)] += dv
                if dp:
                    adds_ph[dkey][(aid, hour)] += dp
                    s["lp"] = ts
        s["v"], s["p"], s["m"] = v, p, ts

    # --- 6. сохранение
    log("Шаг 5: сохранение")
    for e in events:
        days.setdefault(day_key(e[0]), empty_day())["ev"].append(e)
    # реклама за день: 2 = VIP (polepos), 1 = выделение; VIP перекрывает выделение
    today_d = days.setdefault(day_key(run_ts), empty_day())
    pr = today_d.setdefault("pr", {})
    for aid, s in ads_state.items():
        if s.get("ls") == run_ts and (s.get("pp") or s.get("hl")):
            pr[aid] = max(pr.get(aid, 0), 2 if s.get("pp") else 1)
    for dkey, per_ad in adds_pe.items():
        dpe = days.setdefault(dkey, empty_day()).setdefault("pe", {})
        for aid, by in per_ad.items():
            for k, (dv, dp) in by.items():
                cur = dpe.setdefault(aid, {}).setdefault(k, [0, 0])
                cur[0] += dv
                cur[1] += dp
    for dkey in set(adds_a) | set(adds_vh) | set(adds_ph) | set(cov):
        d = days.setdefault(dkey, empty_day())
        for aid, (dv, dp) in adds_a[dkey].items():
            cur = d["a"].setdefault(aid, [0, 0])
            cur[0] += dv
            cur[1] += dp
        vh = Counter({(x[0], x[1], x[2]): x[3] for x in d["vh"]})
        vh.update(adds_vh[dkey])
        d["vh"] = [[k[0], k[1], k[2], n] for k, n in vh.items()]
        ph = Counter({(x[0], x[1]): x[2] for x in d["ph"]})
        ph.update(adds_ph[dkey])
        d["ph"] = [[k[0], k[1], n] for k, n in ph.items()]
        c = Counter(d.get("cov") or {})
        c.update(cov[dkey])
        d["cov"] = dict(c)
    days.setdefault(day_key(run_ts), empty_day())["runs"].append(run_ts)
    cutoff_day = (local(run_ts) - timedelta(days=CUBE_DAYS)).strftime("%Y-%m-%d")
    for dkey in [k for k in days if k < cutoff_day]:
        del days[dkey]

    # раз в запуск — дописываем сырые замеры за день (хранятся 120 дней)
    for dkey, rows in raw_rows.items():
        old = kv.get_json(f"raw:{dkey}", default=[]) or []
        kv.put_json(f"raw:{dkey}", old + rows, ttl_seconds=RAW_TTL_DAYS * 86400)

    # чистка: старые неактивные объявления
    keep_after = run_ts - ADS_KEEP_DAYS * 86400
    for aid in [a for a, s in ads_state.items() if not s.get("act") and (s.get("ls") or 0) < keep_after]:
        del ads_state[aid]
        tries.pop(aid, None)

    state["last_run"] = run_ts
    state["max_id"] = max([prev_max_id] + [int(a) for a in ads_state if a.isdigit()])
    state["polygon"] = polys[0] if polys else None
    size_state = kv.put_json("state", state)
    size_cube = kv.put_json("cube", cube)

    catalog_fields = ("c", "pid", "cn", "t", "r", "a", "fl", "ft", "pu", "ad", "lt", "lt0", "fs", "ls", "act", "fv", "fh", "pb4",
                      "img", "ni", "hl", "pp", "rb", "nw", "v", "p")
    catalog = {
        "generated": run_ts,
        "companies": {k: c["label"] for k, c in companies.items()},
        "promo": cfg.get("promo") or {},
        "profiles": {pid: {"name": p.get("name") or "", "company": p.get("company"), "auto": p.get("auto", 0)}
                     for pid, p in profiles.items()},
        "ads": {aid: {k: s.get(k) for k in catalog_fields if s.get(k) not in (None, "")} for aid, s in ads_state.items()},
    }
    size_cat = kv.put_json("catalog", catalog)

    duration = round(time.time() - t_start)
    status = {
        "last_run": run_ts, "duration_s": duration, "bootstrap": bootstrap,
        "district_complete": district_complete, "full_feeds": full_feeds,
        "stats": dict(STATS), "sizes": {"state": size_state, "cube": size_cube, "catalog": size_cat},
        "polygon_source": state.get("polygon_source"),
    }
    kv.put_json("status", status)
    summary = json.dumps({"sec": duration, "boot": bootstrap, "district_complete": district_complete,
                          "full_feeds": full_feeds, "poly": state.get("polygon_source"), **dict(STATS),
                          "kb": {"state": size_state // 1024, "cube": size_cube // 1024, "catalog": size_cat // 1024}},
                         ensure_ascii=False)
    log("Готово: " + summary)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=collect::{summary}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        # подробности ошибки без данных объявлений
        tb = traceback.format_exc()
        print(tb)
        if os.environ.get("GITHUB_ACTIONS"):
            last = [ln.strip() for ln in tb.strip().splitlines()][-3:]
            print("::error title=collect::" + " | ".join(last)[:900])
        sys.exit(1)
