"""Контрольные проверки быстрого старта; без подключения к Kufar/Cloudflare."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
from fast_start import build_fast_archive, record_sample


class FakeKV:
    def __init__(self):
        self.data = {}
    def get_json(self, key, default=None):
        return self.data.get(key, default)
    def put_json(self, key, obj, ttl_seconds=None):
        self.data[key] = obj
        return 1


class FastStartTest(unittest.TestCase):
    def test_recording_windows_and_no_guessing(self):
        r = {"t": 1000000, "w": {}}
        record_sample(r, ["1", 1000000+1800, 17, 1])
        record_sample(r, ["1", 1000000+6900, 55, 4])
        record_sample(r, ["1", 1000000+7300, 70, 5])
        self.assertEqual(r["w"]["1"][0], 17)
        self.assertEqual(r["w"]["2"][0], 55)
        self.assertEqual(r["w"]["3"][0], 70)

    def test_backfill_and_removed_listing_retained(self):
        kv = FakeKV()
        ts = 1795323600
        from fast_start import day_key
        kv.data["raw:"+day_key(ts)] = [["99",ts+1200,14,1],["99",ts+6600,67,3]]
        state = {"ads":{"99":{"lt0":ts, "act":0,"ls":ts+7200,"nw":1,"t":"Тест", "r":"1"}}}
        res = build_fast_archive(kv,state,{}, {},ts+8000)
        self.assertEqual(res["ads"],1)
        self.assertEqual(kv.data["fast"]["ads"]["99"]["w"]["2"][0],67)
        build_fast_archive(kv,{"ads":{}},{},{},ts+10000)
        self.assertIn("99",kv.data["fast"]["ads"])

if __name__=="__main__":
    unittest.main()
