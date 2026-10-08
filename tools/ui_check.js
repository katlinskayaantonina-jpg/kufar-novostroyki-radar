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
  for (const t of ['overview', 'promo', 'ads', 'employees', 'hours', 'placed', 'works']) {
    await p.click(`[data-tab="${t}"]`);
    await p.waitForTimeout(400);
    out[t] = await p.evaluate(() => ({
      kpis: [...document.querySelectorAll('.kpi .v')].map(e => e.textContent).slice(0, 7).join(' | '),
      rows: document.querySelectorAll('tbody tr').length, cards: document.querySelectorAll('.acard').length,
      bars: document.querySelectorAll('svg path').length,
    }));
  }
  for (const per of ['today', '30', 'all']) {
    await p.click(`[data-period="${per}"]`); await p.click('[data-tab="overview"]'); await p.waitForTimeout(300);
    out['period_' + per] = await p.evaluate(() => [...document.querySelectorAll('.kpi .v')].map(e => e.textContent).slice(0, 3).join(' | '));
  }
  console.log(`::notice title=ui::${JSON.stringify(out)}`);
  console.log(`::notice title=ui_errors::${JSON.stringify(errs.slice(0, 5))}`);
  await b.close();
})();
