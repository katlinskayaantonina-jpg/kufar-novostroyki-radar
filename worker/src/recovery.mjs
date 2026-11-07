const WORKFLOW = "https://api.github.com/repos/katlinskayaantonina-jpg/kufar-novostroyki-radar/actions/workflows/collect.yml";
const SLOT_MS = 30 * 60 * 1000;

export function collectionSlot(scheduledMs) {
  const local = new Date(scheduledMs + 3 * 60 * 60 * 1000);
  const hour = local.getUTCHours();
  const minute = local.getUTCMinutes();
  // Midnight is the last slot. 00:15 is its retry.
  if (hour < 8 && (hour !== 0 || minute >= 30)) return null;
  return Math.floor(scheduledMs / SLOT_MS) * SLOT_MS;
}

export async function runCollectionSlot(scheduledMs, token, request = fetch) {
  const slot = collectionSlot(scheduledMs);
  if (slot === null) return "night_pause";
  if (!token) throw new Error("GitHub Actions token is missing");

  const headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json",
    "User-Agent": "new-buildings-radar-watchdog",
  };
  const runs = await request(`${WORKFLOW}/runs?branch=main&per_page=10`, {
    headers, signal: AbortSignal.timeout(10000),
  });
  if (!runs.ok) throw new Error(`GitHub list runs: HTTP ${runs.status}`);

  const { workflow_runs: recentRuns } = await runs.json();
  if (!Array.isArray(recentRuns)) throw new Error("GitHub response missing workflow_runs");
  if (recentRuns.some(run => run.status !== "completed")) return "run_active";
  if (recentRuns.some(run => run.conclusion === "success" &&
      Date.parse(run.created_at) >= slot)) return "slot_complete";

  const dispatch = await request(`${WORKFLOW}/dispatches`, {
    method: "POST", headers, body: JSON.stringify({ ref: "main" }),
    signal: AbortSignal.timeout(10000),
  });
  if (!dispatch.ok) throw new Error(`GitHub dispatch: HTTP ${dispatch.status}`);
  return "dispatched";
}
