const WORKFLOW = "https://api.github.com/repos/katlinskayaantonina-jpg/kufar-novostroyki-radar/actions/workflows/collect.yml";
const RECENT_RUN_MS = 30 * 60 * 1000;

export async function recoverCollection(state, token, nowMs, request = fetch) {
  if (!token || !["stale", "unknown"].includes(state)) return "skipped";

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
  if (recentRuns.some(run => run.status !== "completed" ||
      nowMs - Date.parse(run.created_at) < RECENT_RUN_MS)) return "recent_run";

  const dispatch = await request(`${WORKFLOW}/dispatches`, {
    method: "POST", headers, body: JSON.stringify({ ref: "main" }),
    signal: AbortSignal.timeout(10000),
  });
  if (!dispatch.ok) throw new Error(`GitHub dispatch: HTTP ${dispatch.status}`);
  return "dispatched";
}
