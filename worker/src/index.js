import page from "./dashboard.html";

const DATA_KEYS = new Set(["catalog", "cube", "status"]);

function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length || !a.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

const NOT_FOUND = () => new Response("Not found", { status: 404, headers: { "X-Robots-Tag": "noindex", "Cache-Control": "no-store" } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/robots.txt") return new Response("User-agent: *\nDisallow: /\n", { headers: { "Content-Type": "text/plain" } });
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
};
