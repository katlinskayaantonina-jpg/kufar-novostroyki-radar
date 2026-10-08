"""Граница района: из KML (Google Мои карты) или, пока его нет, по точкам объявлений района Kufar."""
from __future__ import annotations

import math
import re
from pathlib import Path


def load_kml_polygons(path: Path) -> list[list[tuple[float, float]]]:
    """Возвращает список многоугольников [(lat, lon), ...] из KML."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    polys = []
    for block in re.findall(r"<coordinates>(.*?)</coordinates>", text, flags=re.S):
        pts = []
        for tok in block.split():
            parts = tok.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                pts.append((lat, lon))
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def dist_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = (a[0] - b[0]) * 111.0
    dlon = (a[1] - b[1]) * 111.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon)


def hull_from_district_points(points: list[tuple[float, float]], keep_share: float = 0.98) -> list[tuple[float, float]]:
    """Оболочка вокруг точек района, без 2% самых дальних (ошибочные метки на карте)."""
    if len(points) < 20:
        return []
    lats = sorted(p[0] for p in points)
    lons = sorted(p[1] for p in points)
    center = (lats[len(lats) // 2], lons[len(lons) // 2])
    ranked = sorted(points, key=lambda p: dist_km(p, center))
    kept = ranked[: max(3, int(len(ranked) * keep_share))]
    return convex_hull(kept)


def inside(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    n = len(poly)
    if n < 3:
        return False
    res = False
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_cross:
                res = not res
        j = i
    return res
