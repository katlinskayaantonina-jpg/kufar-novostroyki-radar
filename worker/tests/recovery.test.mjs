import test from "node:test";
import assert from "node:assert/strict";
import { recoverCollection } from "../src/recovery.mjs";

const now = Date.parse("2026-11-07T08:00:00Z");

test("night pause, fresh data and missing credentials never dispatch", async () => {
  const request = () => assert.fail("unexpected API request");
  assert.equal(await recoverCollection("paused", "token", now, request), "skipped");
  assert.equal(await recoverCollection("fresh", "token", now, request), "skipped");
  assert.equal(await recoverCollection("stale", undefined, now, request), "skipped");
});

test("queued, active and recently completed runs suppress duplicate dispatch", async () => {
  for (const [status, age] of [["queued", 40], ["in_progress", 40], ["completed", 14]]) {
    const request = async (_url, options) => {
      assert.equal(options.method, undefined);
      return Response.json({workflow_runs: [{
        status, created_at: new Date(now - age * 60_000).toISOString(),
      }]});
    };
    assert.equal(await recoverCollection("stale", "token", now, request), "recent_run");
  }
});

test("stale data and an empty run queue dispatch main; API failures surface", async () => {
  const request = async (url, options) => {
    if (url.includes("/runs?")) return Response.json({workflow_runs: []});
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), {ref:"main"});
    return new Response(null, {status:204});
  };
  assert.equal(await recoverCollection("stale", "token", now, request), "dispatched");
  await assert.rejects(recoverCollection("stale", "token", now, async () =>
    new Response(null, {status:403})), /list runs: HTTP 403/);
});
