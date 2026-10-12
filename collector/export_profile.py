"""Выгрузка всех актуальных объявлений одного профиля Kufar + сверка с базой радара.

Только чтение: Kufar (поиск по профилю) и Cloudflare KV. Ничего не меняет.
Результат шифруется ключом RADAR_KEY (репозиторий открытый).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import radar  # noqa: E402
from crypto import encrypt  # noqa: E402
from kv import KV  # noqa: E402

MSK = timezone(timedelta(hours=3))
PID = os.environ["PROFILE_ID"].strip()
NAME = os.environ.get("PROFILE_NAME", "").strip()


def dt(ts):
    return datetime.fromtimestamp(ts, MSK).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


def params_flat(ad: dict) -> dict:
    out = {}
    for x in ad.get("ad_parameters") or []:
        if isinstance(x, dict) and x.get("p"):
            vl = x.get("vl")
            if isinstance(vl, list):
                vl = ", ".join(str(v) for v in vl if v)
            out[x["p"]] = {"label": x.get("pl"), "value": x.get("v"), "text": vl}
    return out


def acc_flat(ad: dict) -> dict:
    return {x["p"]: x.get("v") for x in (ad.get("account_parameters") or []) if isinstance(x, dict) and x.get("p")}


def main():
    started = int(time.time())
    # 1. Живая выдача Kufar по профилю — все категории, все типы сделок, все страницы
    feeds = {}
    for name, p in (("all", {"atid": PID, "sort": "lst.d"}),
                    ("realty_sell", {"atid": PID, "prn": "1000", "typ": "sell", "sort": "lst.d"}),
                    ("realty_let", {"atid": PID, "prn": "1000", "typ": "let", "sort": "lst.d"})):
        try:
            ads, complete = radar.crawl(p, max_pages=200)
            feeds[name] = {"ads": ads, "complete": complete, "error": None}
        except Exception as e:  # noqa: BLE001
            feeds[name] = {"ads": [], "complete": False, "error": str(e)}
    merged, src = {}, {}
    for name, f in feeds.items():
        for ad in f["ads"]:
            aid = str(ad.get("ad_id") or ad.get("list_id") or "")
            if aid and aid not in merged:
                merged[aid] = ad
            src.setdefault(aid, []).append(name)
    finished = int(time.time())

    # 2. База радара
    kv = KV()
    st = kv.get_json("state", {}) or {}
    sads = st.get("ads", {})
    status = kv.get_json("status", {}) or {}
    radar_mine = {a for a, s in sads.items() if str(s.get("pid") or "") == PID}

    accounts = Counter(str(a.get("account_id") or "") for a in merged.values())
    main_acc = accounts.most_common(1)[0][0] if accounts else ""

    rows, unver = [], []
    for aid, ad in sorted(merged.items(), key=lambda kv_: -(radar.iso_to_ts(kv_[1].get("list_time")) or 0)):
        P, A, s = params_flat(ad), acc_flat(ad), sads.get(aid, {})
        lt = radar.iso_to_ts(ad.get("list_time"))
        eur = next((x.get("price") for x in (ad.get("calculator") or []) if isinstance(x, dict) and str(x.get("currency")) == "EUR"), None)
        g = lambda k, f="text": (P.get(k) or {}).get(f)  # noqa: E731
        cat_label = next((v["text"] for k, v in P.items() if k in ("category", "cat")), None)
        row = {
            "ad_id": aid,
            "url": ad.get("ad_link") or f"https://re.kufar.by/vi/{aid}",
            "profile_id_confirmed": PID,
            "account_id": ad.get("account_id"),
            "seller_name": A.get("name") or A.get("contact_person"),
            "contact_person": A.get("contact_person"),
            "company_unp": A.get("vat_number"),
            "list_time_utc": ad.get("list_time"),
            "list_time_minsk": dt(lt),
            "first_publication_minsk_radar": dt(s.get("lt0")),
            "price_byn_raw": ad.get("price_byn"),
            "price_byn": (int(ad["price_byn"]) / 100) if str(ad.get("price_byn") or "").isdigit() else "",
            "price_usd_raw": ad.get("price_usd"),
            "price_usd": (int(ad["price_usd"]) / 100) if str(ad.get("price_usd") or "").isdigit() else "",
            "price_eur_raw": eur,
            "price_eur": (int(eur) / 100) if str(eur or "").isdigit() else "",
            "currency": ad.get("currency"),
            "category_code": ad.get("category"),
            "category_name": cat_label or "",
            "parent_category_code": ad.get("parent_category") or ad.get("parent"),
            "deal_type": ad.get("type"),
            "object_type": g("re_object_type") or g("property_type") or g("flat_type") or "",
            "rooms": g("rooms", "value"),
            "area_m2": g("size", "value"),
            "floor": g("floor", "value"),
            "floors_total": g("re_number_floors", "value"),
            "new_building": g("flat_new_building", "value"),
            "condition": g("condition"),
            "district": g("re_district"),
            "address": A.get("address") or g("address"),
            "title": ad.get("subject"),
            "photos": len(ad.get("images") or []),
            "highlight": 1 if (ad.get("paid_services") or {}).get("highlight") else 0,
            "vip_polepos": 1 if (ad.get("paid_services") or {}).get("polepos") else 0,
            "seen_in_kufar_profile_feed_minsk": dt(finished),
            "feeds": "+".join(src.get(aid, [])),
            "in_radar_db": 1 if aid in sads else 0,
            "radar_profile_id": s.get("pid") or "",
            "radar_active": s.get("act") or 0,
            "radar_first_seen_minsk": dt(s.get("fs")),
            "radar_last_seen_minsk": dt(s.get("ls")),
            "ownership_method": f"Kufar API: выдача объявлений профиля atid={PID}"
                                + ("; совпадает с профилем в базе радара" if str(s.get("pid") or "") == PID else ""),
            "all_ad_parameters_json": json.dumps(P, ensure_ascii=False),
        }
        reason = []
        if main_acc and str(ad.get("account_id") or "") != main_acc:
            reason.append(f"account_id {ad.get('account_id')} отличается от основного {main_acc}")
        if s.get("pid") and str(s["pid"]) != PID:
            reason.append(f"в базе радара привязано к другому профилю {s['pid']}")
        if reason:
            row["unverified_reason"] = "; ".join(reason)
            unver.append(row)
        else:
            rows.append(row)
    # в радаре числятся за Еленой и активны, но в живой выдаче профиля их нет
    for aid in sorted(radar_mine - set(merged)):
        s = sads[aid]
        if not s.get("act"):
            continue
        unver.append({"ad_id": aid, "url": f"https://re.kufar.by/vi/{aid}", "profile_id_confirmed": "",
                      "radar_profile_id": PID, "title": s.get("t"), "address": s.get("ad"), "rooms": s.get("r"),
                      "area_m2": s.get("a"), "floor": s.get("fl"), "price_byn": s.get("pb"), "price_usd": s.get("pu"),
                      "price_eur": s.get("pe"), "list_time_minsk": dt(s.get("lt")), "radar_last_seen_minsk": dt(s.get("ls")),
                      "unverified_reason": "в базе радара за этим профилем и активно, но в живой выдаче профиля Kufar отсутствует"})

    def to_csv(items):
        buf = io.StringIO()
        keys = []
        for r in items:
            for k in r:
                if k not in keys:
                    keys.append(k)
        w = csv.DictWriter(buf, fieldnames=keys or ["ad_id"], extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
        return ("﻿" + buf.getvalue()).encode("utf-8")

    cats = Counter(f"{r['category_code']} {r['category_name']}".strip() for r in rows)
    info = {
        "profile_id": PID, "profile_name": NAME,
        "source": "Kufar public search API (cre-api.kufar.by, параметр atid = профиль) — живая выдача; сверка с базой радара в Cloudflare KV (radar-data: state, status)",
        "export_started_minsk": dt(started), "export_finished_minsk": dt(finished),
        "feeds": {k: {"ads": len(v["ads"]), "all_pages_read": v["complete"], "error": v["error"]} for k, v in feeds.items()},
        "complete": all(v["complete"] for v in feeds.values()) and not any(v["error"] for v in feeds.values()),
        "ads_confirmed": len(rows), "ads_unverified": len(unver),
        "categories": dict(cats),
        "account_ids_in_feed": dict(accounts),
        "radar": {
            "last_run_minsk": dt(status.get("last_run")),
            "last_run_district_complete": status.get("district_complete"),
            "last_full_profile_feeds_minsk": dt(st.get("last_full_feeds") or st.get("full_feeds_ts") or 0) or "не хранится",
            "radar_scope": "радар хранит только объявления в районе Минск-Мир; объявления в других районах и коммерческая недвижимость в его базе могут отсутствовать",
            "ads_with_this_profile_in_radar": len(radar_mine),
            "ads_with_this_profile_in_radar_active": sum(1 for a in radar_mine if sads[a].get("act")),
            "feed_ads_present_in_radar": sum(1 for r in rows if r["in_radar_db"]),
        },
        "ownership_check": f"объявление входит в выдачу Kufar по профилю atid={PID} (Kufar сам фильтрует по профилю продавца); "
                           "дополнительно: account_id совпадает с основным аккаунтом этой выдачи и в базе радара объявление не привязано к другому профилю",
        "notes": "Ничего не удалялось и не изменялось. Цены *_raw — как отдаёт Kufar (в копейках/центах), без округления.",
    }
    raw = {aid: ad for aid, ad in merged.items()}
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("elena_current_ads.csv", to_csv(rows))
        if unver:
            z.writestr("elena_unverified_ads.csv", to_csv(unver))
        z.writestr("export_info.json", json.dumps(info, ensure_ascii=False, indent=2))
        z.writestr("elena_raw_kufar_api.json", json.dumps(raw, ensure_ascii=False))
    os.makedirs("out", exist_ok=True)
    open("out/export.enc", "wb").write(encrypt(zbuf.getvalue(), os.environ["RADAR_KEY"]))
    keys0 = sorted((next(iter(merged.values())) or {}).keys()) if merged else []
    print("::notice title=export::" + json.dumps({k: info[k] for k in ("feeds", "complete", "ads_confirmed", "ads_unverified", "categories", "account_ids_in_feed")}, ensure_ascii=False)[:900])
    print("::notice title=radar::" + json.dumps(info["radar"], ensure_ascii=False)[:900])
    print("::notice title=keys::" + json.dumps(keys0)[:900])


main()
