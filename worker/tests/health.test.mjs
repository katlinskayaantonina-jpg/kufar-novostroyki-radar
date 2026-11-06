import test from "node:test";
import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { freshnessState, isCollectionExpected, readLastRun, watchdogAlive } from "../src/health.mjs";

const ts = (year, month, day, hour, minute) =>
  Math.floor(Date.UTC(year, month - 1, day, hour - 3, minute) / 1000);

test("fresh during collection hours", () => {
  const now = ts(2026, 11, 6, 14, 0);
  assert.deepEqual(freshnessState(now - 30 * 60, now), {
    state:"fresh", last_run: now - 30 * 60, age_minutes:30
  });
});

test("stale after 90 minutes during collection hours", () => {
  const now = ts(2026, 11, 6, 22, 6);
  assert.equal(freshnessState(ts(2026, 11, 6, 20, 0), now).state, "stale");
  assert.equal(freshnessState(now - 90 * 60, now).state, "fresh");
  assert.equal(freshnessState(now - 91 * 60, now).state, "stale");
});

test("nightly pause; startup and midnight windows", () => {
  assert.equal(isCollectionExpected(ts(2026, 11, 7, 0, 30)), true);
  assert.equal(isCollectionExpected(ts(2026, 11, 7, 1, 0)), false);
  assert.equal(isCollectionExpected(ts(2026, 11, 7, 8, 30)), false);
  assert.equal(isCollectionExpected(ts(2026, 11, 7, 8, 45)), true);
  assert.equal(freshnessState(ts(2026, 11, 6, 20, 0),
    ts(2026, 11, 7, 3, 0)).state, "paused");
});

test("unknown and future data", () => {
  const now = ts(2026, 11, 6, 13, 0);
  assert.equal(freshnessState(null, now).state, "unknown");
  assert.equal(freshnessState(now + 10000, now).state, "unknown");
});

test("read gzip status saved by Python KV client", async () => {
  const lastRun = 1794000000;
  const payload = gzipSync(Buffer.from(JSON.stringify({last_run:lastRun})));
  const env = {DATA:{get:async()=>payload.buffer.slice(
    payload.byteOffset, payload.byteOffset + payload.byteLength)}};
  assert.equal(await readLastRun(env), lastRun);
});

test("watchdog heartbeat expires independently", () => {
  const now = ts(2026, 11, 6, 14, 0);
  assert.equal(watchdogAlive({checked_at:now - 20*60}, now), true);
  assert.equal(watchdogAlive({checked_at:now - 36*60}, now), false);
  assert.equal(watchdogAlive(null, now), false);
});
