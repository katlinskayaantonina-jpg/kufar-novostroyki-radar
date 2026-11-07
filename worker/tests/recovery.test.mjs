import test from "node:test";
import assert from "node:assert/strict";
import { collectionSlot, runCollectionSlot } from "../src/recovery.mjs";

const utc = (hour, minute) => Date.UTC(2026, 10, 7, hour, minute);
const slot = utc(8, 0);
const run = (status, created, conclusion) => ({
  status, created_at: new Date(created).toISOString(), conclusion,
});

test("Minsk opening, half-hour slots, midnight retry and night pause", () => {
  assert.equal(collectionSlot(utc(4, 45)), null);
  assert.equal(collectionSlot(utc(5, 0)), utc(5, 0));
  assert.equal(collectionSlot(utc(5, 15)), utc(5, 0));
  assert.equal(collectionSlot(utc(5, 30)), utc(5, 30));
  assert.equal(collectionSlot(utc(21, 15)), utc(21, 0));
  assert.equal(collectionSlot(utc(21, 30)), null);
});

test("night pause uses no API and a missing token surfaces during the day", async () => {
  const request = () => assert.fail("unexpected API request");
  assert.equal(await runCollectionSlot(utc(4, 45), "token", request), "night_pause");
  await assert.rejects(runCollectionSlot(slot, undefined, request), /token is missing/);
});

test("active jobs and slots already completed do not dispatch again", async () => {
  const list = job => async (_url, options) => {
    assert.equal(options.method, undefined);
    return Response.json({workflow_runs: [job]});
  };
  for (const status of ["queued", "in_progress"]) {
    assert.equal(await runCollectionSlot(slot, "token",
      list(run(status, slot - 1000))), "run_active");
  }
  assert.equal(await runCollectionSlot(slot + 900_000, "token",
    list(run("completed", slot + 1000, "success"))), "slot_complete");
});

test("a previous successful slot and a failed current slot both permit dispatch", async () => {
  for (const job of [run("completed", slot - 1000, "success"),
                     run("completed", slot + 1000, "failure")]) {
    const request = async (url, options) => {
      if (url.includes("/runs?")) return Response.json({workflow_runs: [job]});
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), {ref:"main"});
      return new Response(null, {status:204});
    };
    assert.equal(await runCollectionSlot(slot + 900_000, "token", request), "dispatched");
  }
});

test("GitHub API failure surfaces for the watchdog", async () => {
  await assert.rejects(runCollectionSlot(slot, "token", async () =>
    new Response(null, {status:403})), /list runs: HTTP 403/);
});
