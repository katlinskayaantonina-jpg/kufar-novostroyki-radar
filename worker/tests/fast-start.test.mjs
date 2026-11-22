import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('../src/dashboard.html', import.meta.url), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0]
  .split(/\/\/ ---------- старт\r?\n\(async function\(\)\{/)[0];
const document = { querySelector: () => ({ style:{} }), addEventListener(){} };
const context = vm.createContext({ document, console, URLSearchParams,
  location:{search:''},innerWidth:1000,localStorage:{getItem:()=>null,setItem(){}} });
vm.runInContext(script,context);

const ts = Date.parse('2026-11-20T09:00:00+03:00')/1000;
const ad = { nw:1,c:'et', r:1,t:'Проверка', pe:50000,a:40,act:0,ls:ts+9000,seller:'Тестовый агент' };
const archive = {
 t:ts,a:ad,w:{'1':[50,1,ts+1800],'2':[120,6,ts+6900]},
 points:[[ts+1800,50,1],[ts+6900,120,6]]
};
const late = {
 t:ts+60,a:{...ad,t:'Неполные замеры'},w:{'2':[600,30,ts+60+3600]},
 points:[[ts+60+3600,600,30]]
};
context.fixtures={cat:{ads:{},profiles:{},companies:{et:'Этажи'}},
 cube:{days:{'2026-11-20':{a:{},ph:[],vh:[],ev:[],cov:{},runs:[]}}},
 fast:{ads:{'100':archive,'101':late}}};
vm.runInContext('CAT=fixtures.cat;CUBE=fixtures.cube;FAST_DATA=fixtures.fast;S.period="custom";S.from="2026-11-20";S.to="2026-11-20";S.company="all";S.newOnly=false;',context);

test('removed organic ad is retained but incomplete observations are excluded',()=>{
 const rows=vm.runInContext('fsRows()',context);
 assert.equal(rows.length,2);
 assert.equal(rows.find(r=>r.id==='100').complete,true);
 assert.equal(rows.find(r=>r.id==='101').complete,false);
 const output=vm.runInContext('viewFast()',context);
 assert.match(output,/Быстрый старт/);
 assert.match(output,/Проверка/);
 assert.doesNotMatch(output,/<div class="at">Неполные замеры/);
});

test('views and phone openings have separate rankings',()=>{
 const out1=vm.runInContext('viewFast()',context);
 assert.match(out1,/120/);
 vm.runInContext('FS.metric="p"',context);
 const out2=vm.runInContext('viewFast()',context);
 assert.match(out2,/открытий номера/);
 assert.match(out2,/Быстрый старт/);
});
