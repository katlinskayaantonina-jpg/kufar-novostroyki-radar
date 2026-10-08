"""Минимальный клиент Cloudflare Workers KV через REST API."""
from __future__ import annotations

import gzip
import json
import os
import re
import time

import requests

API = "https://api.cloudflare.com/client/v4"
NAMESPACE_TITLE = "radar-data"


def clean_token(raw: str) -> str:
    """Секрет мог быть вставлен целой командой `curl ... Bearer <ключ>` — достаём сам ключ."""
    raw = (raw or "").strip()
    m = re.search(r"Bearer\s+([A-Za-z0-9_\-]+)", raw)
    if m:
        return m.group(1)
    return re.sub(r"\s+", "", raw)


class KV:
    def __init__(self, token: str | None = None, account: str | None = None, namespace_id: str | None = None):
        self.token = clean_token(token or os.environ.get("CLOUDFLARE_API_TOKEN", ""))
        self.account = (account or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")).strip()
        if not self.token or not self.account:
            raise RuntimeError("Нет CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {self.token}"
        self.ns = namespace_id or self.ensure_namespace()

    def _req(self, method: str, url: str, **kw):
        last = None
        for i in range(5):
            try:
                r = self.s.request(method, url, timeout=120, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = RuntimeError(f"KV HTTP {r.status_code}")
                    time.sleep(2 * (i + 1))
                    continue
                return r
            except requests.RequestException as e:
                last = e
                time.sleep(2 * (i + 1))
        raise last  # type: ignore[misc]

    def ensure_namespace(self) -> str:
        base = f"{API}/accounts/{self.account}/storage/kv/namespaces"
        r = self._req("GET", base, params={"per_page": 100})
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"KV list namespaces failed: {data.get('errors')}")
        for ns in data.get("result") or []:
            if ns.get("title") == NAMESPACE_TITLE:
                return ns["id"]
        r = self._req("POST", base, json={"title": NAMESPACE_TITLE})
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"KV create namespace failed: {data.get('errors')}")
        return data["result"]["id"]

    def _url(self, key: str) -> str:
        return f"{API}/accounts/{self.account}/storage/kv/namespaces/{self.ns}/values/{requests.utils.quote(key, safe='')}"

    def get_bytes(self, key: str) -> bytes | None:
        r = self._req("GET", self._url(key))
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise RuntimeError(f"KV GET {key}: HTTP {r.status_code} {r.text[:200]}")
        return r.content

    def put_bytes(self, key: str, data: bytes, ttl_seconds: int | None = None) -> None:
        params = {"expiration_ttl": int(ttl_seconds)} if ttl_seconds else None
        r = self._req("PUT", self._url(key), data=data, params=params,
                      headers={"Content-Type": "application/octet-stream"})
        ok = r.status_code == 200 and (r.json() or {}).get("success")
        if not ok:
            raise RuntimeError(f"KV PUT {key}: HTTP {r.status_code} {r.text[:200]}")

    def get_json(self, key: str, default=None):
        raw = self.get_bytes(key)
        if raw is None:
            return default
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))

    def put_json(self, key: str, obj, ttl_seconds: int | None = None) -> int:
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gz = gzip.compress(raw, compresslevel=9)
        self.put_bytes(key, gz, ttl_seconds)
        return len(gz)
