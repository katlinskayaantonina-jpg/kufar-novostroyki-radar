import page from "./dashboard.html";
import { freshnessState, readLastRun, watchdogAlive } from "./health.mjs";

const DATA_KEYS = new Set(["catalog", "cube", "status"]);
const HEALTH_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Robots-Tag": "noindex, nofollow",
};

function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length || !a.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

const NOT_FOUND = () => new Response("Not found", { status: 404, headers: { "X-Robots-Tag": "noindex", "Cache-Control": "no-store" } });

async function publicHealth(env) {
  const now = Math.floor(Date.now() / 1000);
  try {
    const [lastRun, watchdog] = await Promise.all([
      readLastRun(env),
      env.DATA.get("watchdog", { type: "json" }),
    ]);
    // Only operational timestamps/status; no customer, ad, profile or secret data.
    const freshness = freshnessState(lastRun, now);
    return new Response(JSON.stringify({
      ...freshness,
      checked_at: now,
      watchdog_last_checked: watchdog?.checked_at ?? null,
      watchdog_alive: watchdogAlive(watchdog, now),
    }), { headers: HEALTH_HEADERS });
  } catch (error) {
    console.error("Radar freshness check failed:", String(error));
    return new Response(JSON.stringify({ state:"error", checked_at:now, watchdog_alive:false }),
      { status:503, headers:HEALTH_HEADERS });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/robots.txt") return new Response("User-agent: *\nDisallow: /\n", { headers: { "Content-Type": "text/plain" } });
    if (url.pathname === "/health" && request.method === "GET") return publicHealth(env);
    if (!same(url.searchParams.get("k") || "", env.RADAR_KEY || "")) return NOT_FOUND();

    if (url.pathname === "/") {
      return new Response(page, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "no-store",
          "X-Robots-Tag": "noindex, nofollow",
          "Referrer-Policy": "no-referrer",
        },
      });
    }
    const m = url.pathname.match(/^\/d\/([a-z]+)$/);
    if (m && DATA_KEYS.has(m[1])) {
      const body = await env.DATA.get(m[1], { type: "arrayBuffer" });
      if (!body) return new Response("{}", { status: 404, headers: { "Content-Type": "application/json" } });
      return new Response(body, {
        encodeBody: "manual",
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Content-Encoding": "gzip",
          "Cache-Control": "private, max-age=60",
          "X-Robots-Tag": "noindex",
        },
      });
    }
    return NOT_FOUND();
  },

  async scheduled(controller, env) {
    const now = Math.floor(Date.now() / 1000);
    let state = "error", lastRun = null;
    try {
      lastRun = await readLastRun(env);
      state = freshnessState(lastRun, now).state;
    } catch (error) {
      console.error("Watchdog could not read radar status:", String(error));
    }
    await env.DATA.put("watchdog", JSON.stringify({
      checked_at: now, state, last_run: lastRun,
    }), { expirationTtl: 2 * 24 * 3600 });
    console.log("radar-watchdog", JSON.stringify({state, checked_at:now}));
  },
};
