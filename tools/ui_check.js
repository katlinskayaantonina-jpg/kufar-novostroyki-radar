// Открывает настоящий дашборд в браузере и сообщает только ошибки и количество строк/цифры KPI.
const { chromium } = require('playwright');
(async () => {
  const url = process.env.URL;
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.waitForTimeout(1500);
  const out = { status: await p.textContent('#status') };
  for (const t of ['overview', 'promo', 'ads', 'employees', 'hours', 'placed', 'organic', 'promoted']) {
    await p.click(`[data-tab="${t}"]`);
    await p.waitForTimeout(400);
    out[t] = await p.evaluate(() => ({
      kpis: [...document.querySelectorAll('.kpi .v')].map(e => e.textContent).slice(0, 7).join(' | '),
      rows: document.querySelectorAll('tbody tr').length, cards: document.querySelectorAll('.acard').length, h3: [...document.querySelectorAll('h3.sec')].map(e => e.textContent).join(' / ').slice(0, 200),
      bars: document.querySelectorAll('svg path').length,
    }));
  }
  for (const per of ['today', '30', 'all']) {
    await p.click(`[data-period="${per}"]`); await p.click('[data-tab="overview"]'); await p.waitForTimeout(300);
    out['period_' + per] = await p.evaluate(() => [...document.querySelectorAll('.kpi .v')].map(e => e.textContent).slice(0, 3).join(' | '));
  }
  console.log(`::notice title=ui::${JSON.stringify(out)}`);
  const pk = await p.evaluate(() => { try { const m = {}; for (const x of pPackages()) { const r = m[x.agent] || (m[x.agent] = {turbo: 0, express: 0, repeat: 0, before: 0}); r[x.package]++; if (x.before) r.before++; } const ads = {}; for (const x of pPackages()) ads[x.ad_id] = (ads[x.ad_id] || 0) + 1; for (const [id, n] of Object.entries(ads)) if (n > 1) { const ag = pAgent(id); m[ag].repeat += n - 1; } return m; } catch (e) { return String(e); } });
  const eff = await p.evaluate(() => { try { const days = Object.keys(CUBE.days).sort(); const P = promoData(days); const want = ["Барашенко","Борискин","Довгун","Хатков"];
    const rows = pEfficiency(P, days).filter(r => want.some(w => r.agent.includes(w))).map(r => ({a: r.agent, t: r.turbo, e: r.express, b: r.bumps, paid: Math.round(r.paid*10)/10, worked: Math.round(r.worked*10)/10, v: r.views, ph: r.phones, rp: r.rubPhone == null ? null : Math.round(r.rubPhone*100)/100}));
    const all = pPackages().filter(x => want.some(w => x.agent.includes(w))); const pre = {}; for (const x of all) if (x.before) pre[x.agent] = (pre[x.agent]||0) + 1;
    const pd = pAggregate(P); const ad = {}; for (const r of pd) if (want.some(w => r.agent.includes(w))) ad[r.agent] = {adDays: r.adDays, v: r.views, p: r.phones};
    const vip = {}, hl = {}; for (const x of P.promoDaily) if (want.some(w => x.agent.includes(w))) { const m = x.promo_status === "vip" ? vip : hl; m[x.agent] = (m[x.agent]||0) + 1; }
    return {from: days[0], to: days[days.length-1], rows, pre, ad, vip, hl}; } catch (e) { return String(e); } });
  console.log(`::notice title=eff::${JSON.stringify(eff).slice(0, 1800)}`);
  const dm = await p.evaluate(() => { try { const pid = Object.entries(CAT.profiles).find(([k, v]) => (v.name || "").includes("Спиридонов"))?.[0]; S.emps = new Set(["p:" + pid]); S.period = "today"; S.tab = "ads"; render();
    return {pid, h3: [...document.querySelectorAll("h3.sec")].map(e => e.textContent), cards: [...document.querySelectorAll(".acard")].slice(0, 13).map(e => (e.textContent.match(/Размещено [0-9.: ]+/) || [""])[0].trim())}; } catch (e) { return String(e); } });
  console.log(`::notice title=dmitry::${JSON.stringify(dm).slice(0, 900)}`);
  console.log(`::notice title=packages::${JSON.stringify(pk).slice(0, 900)}`);
  console.log(`::notice title=ui_errors::${JSON.stringify(errs.slice(0, 5))}`);
  await b.close();
})();
