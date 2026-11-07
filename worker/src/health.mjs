// Independent freshness calculation for the Minsk new-buildings radar.
export const STALE_AFTER_SECONDS = 90 * 60;
export const WATCHDOG_LATE_AFTER_SECONDS = 35 * 60;

// Data collection normally runs 08:00–00:00 Minsk.
// Ignore the expected overnight gap; allow time for each collection to finish.
export function isCollectionExpected(nowSeconds) {
  const secondOfDay = ((nowSeconds + 3 * 3600) % 86400 + 86400) % 86400;
  const minutes = Math.floor(secondOfDay / 60);
  return minutes >= 8 * 60 + 45 || minutes < 45;
}

export function freshnessState(lastRun, nowSeconds = Math.floor(Date.now() / 1000)) {
  const last = Number(lastRun);
  const valid = Number.isFinite(last) && last > 0 && last <= nowSeconds + 300;
  const ageSeconds = valid ? Math.max(0, nowSeconds - last) : null;
  const state = !isCollectionExpected(nowSeconds) ? "paused" :
    !valid ? "unknown" :
    ageSeconds > STALE_AFTER_SECONDS ? "stale" : "fresh";
  return {
    state,
    last_run: valid ? Math.floor(last) : null,
    age_minutes: ageSeconds === null ? null : Math.floor(ageSeconds / 60),
  };
}

export async function readLastRun(env) {
  const raw = await env.DATA.get("status", { type: "arrayBuffer" });
  if (!raw) return null;
  const bytes = new Uint8Array(raw);
  const isGzip = bytes[0] === 0x1f && bytes[1] === 0x8b;
  const text = isGzip
    ? await new Response(new Response(raw).body.pipeThrough(new DecompressionStream("gzip"))).text()
    : new TextDecoder().decode(bytes);
  const status = JSON.parse(text);
  return status?.last_run ?? null;
}

export function watchdogAlive(watchdog, nowSeconds = Math.floor(Date.now() / 1000)) {
  const last = Number(watchdog?.checked_at);
  return Number.isFinite(last) && last > 0
    && nowSeconds - last >= -300 && nowSeconds - last <= WATCHDOG_LATE_AFTER_SECONDS;
}
