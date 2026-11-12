"""
Builds a local website (site/index.html + site/data.js) after every run.
Open site/index.html in any browser – no server, no internet, no Claude needed.

    python3 pw_site.py            # rebuild from the latest run folder
"""
import json, re, sqlite3, datetime as dt, html
from pathlib import Path

HERE = Path(__file__).resolve().parent
import os
SITE = Path(os.environ.get("SITE_DIR", HERE / "site"))

def _hist(db_path, days=120):
    if not db_path.exists(): return {}
    import importlib.util
    spec = importlib.util.spec_from_file_location("catalog", HERE / "catalog.py"); cat = importlib.util.module_from_spec(spec); spec.loader.exec_module(cat)
    return cat.History(db_path).series(days)

def build(run_dir, date):
    run_dir = Path(run_dir)
    load = lambda n, d=None: json.loads((run_dir / n).read_text(encoding="utf-8")) if (run_dir / n).exists() else d
    items = load("items.json", [])
    allit = load("all_items.json", []) or items
    extra = load("site_extra.json", {})
    hist = _hist(HERE / "history.sqlite")
    promo = {(i["store"], i["name"]): i for i in items}

    # cheapest price per model code across stores
    def keys(n):
        return {re.sub(r"[^A-Za-z0-9]", "", t).upper() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/.+]*", n)
                if len(re.sub(r"[^A-Za-z0-9]", "", t)) >= 6 and re.search(r"[A-Za-z]", t) and re.search(r"\d", t)}
    best = {}
    for a in allit:
        for k in keys(a["name"]):
            if k not in best or a["p"] < best[k][0]: best[k] = (a["p"], a["store"])

    rows = []
    for a in allit:
        i = promo.get((a["store"], a["name"]), {})
        cheapest = min((best[k] for k in keys(a["name"]) if k in best), default=None)
        h = hist.get(f"{a['store']}|{a.get('u','')}|{a['name']}", [])
        rows.append([
            a["store"], a.get("cat", ""), a["name"], a["p"], a.get("o") or 0, a.get("l") or i.get("l_used") or 0,
            i.get("v", ""), i.get("mv", ""), (i.get("mkt") or 0), a.get("u", ""),
            cheapest[0] if cheapest and cheapest[1] != a["store"] else 0, cheapest[1] if cheapest and cheapest[1] != a["store"] else "",
            h[-60:],
        ])
    data = {"date": date, "rows": rows, "summary": extra.get("summary", []), "watch": extra.get("watch", []),
            "drops": extra.get("drops", []), "report": (run_dir / "report.txt").read_text(encoding="utf-8") if (run_dir / "report.txt").exists() else "",
            "cols": ["store", "cat", "name", "price", "old", "low30", "verdict", "market_verdict", "market_low", "url", "xs_price", "xs_store", "hist"]}
    SITE.mkdir(exist_ok=True)
    for old_ in SITE.glob("data*.js"): old_.unlink()
    rows_ = data.pop("rows"); CH = 15000          # files stay well under Cloudflare Pages' 25 MB limit
    parts = [rows_[k:k + CH] for k in range(0, len(rows_), CH)] or [[]]
    (SITE / "data.js").write_text("window.DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";window.DATA.rows=[];", encoding="utf-8")
    for k, part in enumerate(parts):
        (SITE / f"data-{k}.js").write_text("window.DATA.rows.push(..." + json.dumps(part, ensure_ascii=False, separators=(",", ":")) + ");", encoding="utf-8")
    page = PAGE.replace('<script src="data.js"></script>', '<script src="data.js"></script>' + "".join(f'<script src="data-{k}.js"></script>' for k in range(len(parts))))
    (SITE / "index.html").write_text(page, encoding="utf-8")
    return SITE / "index.html"

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Price Watch Belgrade</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mut:#6b6b66;--line:#e4e4df;--acc:#2563eb;--good:#15803d;--bad:#b91c1c;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecece8;--mut:#9b9b95;--line:#33332f;--acc:#60a5fa;--good:#4ade80;--bad:#f87171;--warn:#fbbf24}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:18px 20px 0;max-width:1300px;margin:auto}h1{margin:0;font-size:22px}.sub{color:var(--mut)}
nav{display:flex;gap:4px;margin-top:14px;flex-wrap:wrap}nav button{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:7px 14px;border-radius:999px;cursor:pointer;font:inherit}
nav button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
main{max-width:1300px;margin:auto;padding:16px 20px 60px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.filters input,.filters select{padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font:inherit}
.filters input[type=search]{flex:1;min-width:220px}.filters label{white-space:nowrap}.filters button{padding:7px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);cursor:pointer}table{width:100%;border-collapse:collapse}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-weight:600;color:var(--mut);cursor:pointer;white-space:nowrap;position:sticky;top:0;background:var(--card)}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr:hover td{background:color-mix(in srgb,var(--acc) 6%,transparent)}a{color:var(--acc);text-decoration:none}
.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:12px;border:1px solid var(--line);white-space:nowrap}
.g{color:var(--good);border-color:var(--good)}.b{color:var(--bad);border-color:var(--bad)}.w{color:var(--warn);border-color:var(--warn)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.kpi b{display:block;font-size:22px}.mut{color:var(--mut)}.wrap{overflow:auto;max-height:70vh}pre{white-space:pre-wrap;margin:0;font:13px/1.5 ui-monospace,Menlo,monospace}
.spark{width:90px;height:24px}#tbl td:nth-child(2){min-width:300px}#tbl td:last-child{min-width:100px}#modal{position:fixed;inset:0;background:#0008;display:none;align-items:center;justify-content:center;padding:16px}
#modal .card{max-width:720px;width:100%}.pager{display:flex;gap:8px;align-items:center;margin-top:10px}.pager button{padding:5px 10px}
@media(max-width:700px){.hide-s{display:none}}
</style></head><body>
<header><h1>Price Watch Belgrade</h1><div class="sub" id="sub"></div>
<nav id="nav"><button data-t="search" class="on">Search all articles</button><button data-t="deals">Real deals &amp; fakes</button>
<button data-t="drops">Price drops</button><button data-t="watch">Watch items</button><button data-t="stores">Stores</button><button data-t="report">Today's report</button></nav></header>
<main id="main"></main>
<div id="modal"><div class="card" id="mbody"></div></div>
<script src="data.js"></script>
<script>
const D=window.DATA, C=Object.fromEntries(D.cols.map((c,i)=>[c,i])), R=D.rows;
const f=n=>n?Number(n).toLocaleString('sr-RS'):'', pct=x=>(x*100).toFixed(0)+'%', esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('sub').textContent=`Data from ${D.date} · ${R.length.toLocaleString()} articles · stores: ${[...new Set(R.map(r=>r[0]))].join(', ')}`;
function vpill(v){ if(!v) return ''; const c=/^REAL CUT|BELOW|BUY|BEST/.test(v)?'g':/RAISED|FAKE|SKIP/.test(v)?'b':'w'; return `<span class="pill ${c}">${esc(v.replace(' – ',' – '))}</span>`; }
function spark(h){ if(!h||h.length<2) return ''; const ps=h.map(x=>x[1]), mn=Math.min(...ps), mx=Math.max(...ps), W=90,H=24;
  const pts=ps.map((p,i)=>`${(i/(ps.length-1)*W).toFixed(1)},${(mx===mn?H/2:H-2-(p-mn)/(mx-mn)*(H-4)).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${W} ${H}"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${pts}"/></svg>`; }
function chart(h){ if(!h||h.length<1) return '<p class="mut">No history yet – it builds up with each daily run.</p>';
  const ps=h.map(x=>x[1]), mn=Math.min(...ps)*0.98, mx=Math.max(...ps)*1.02, W=660,H=220,L=60,B=24;
  const x=i=>L+(h.length<2?0:i/(h.length-1)*(W-L-10)), y=p=>H-B-(p-mn)/(mx-mn||1)*(H-B-10);
  let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%">`; for(const t of [mn,(mn+mx)/2,mx]) s+=`<text x="4" y="${y(t)+4}" font-size="11" fill="currentColor" opacity=".6">${f(Math.round(t))}</text><line x1="${L}" x2="${W}" y1="${y(t)}" y2="${y(t)}" stroke="currentColor" opacity=".12"/>`;
  s+=`<polyline fill="none" stroke="var(--acc)" stroke-width="2" points="${h.map((d,i)=>x(i)+','+y(d[1])).join(' ')}"/>`;
  h.forEach((d,i)=>{ if(i===0||i===h.length-1||h.length<12) s+=`<circle cx="${x(i)}" cy="${y(d[1])}" r="3" fill="var(--acc)"><title>${d[0]}: ${f(d[1])}</title></circle>`; });
  s+=`<text x="${L}" y="${H-6}" font-size="11" fill="currentColor" opacity=".6">${h[0][0]}</text><text x="${W-10}" y="${H-6}" font-size="11" text-anchor="end" fill="currentColor" opacity=".6">${h[h.length-1][0]}</text></svg>`; return s; }
function openItem(k){ const r=R[k]; const same=R.filter(x=>x!==r && keyset(x[2]).some(z=>keyset(r[2]).includes(z))).sort((a,b)=>a[3]-b[3]).slice(0,8);
  document.getElementById('mbody').innerHTML=`<div style="display:flex;justify-content:space-between;gap:10px"><h3 style="margin:0">${esc(r[2])}</h3><button onclick="closeM()">✕</button></div>
  <p class="mut">${esc(r[0])} · ${esc(r[1])}${r[C.url]?` · <a href="${esc(r[C.url])}" target="_blank">open in store ↗</a>`:''}</p>
  <div class="kpis"><div class="kpi"><span class="mut">Price</span><b>${f(r[3])}</b></div><div class="kpi"><span class="mut">Crossed-out</span><b>${f(r[4])||'–'}</b></div>
  <div class="kpi"><span class="mut">30-day low</span><b>${f(r[5])||'–'}</b></div><div class="kpi"><span class="mut">Market low</span><b>${f(r[8])||'–'}</b></div></div>
  <p>${vpill(r[6])} ${vpill(r[7])}</p>${chart(r[C.hist])}
  ${same.length?`<h4>Same model at other stores</h4><table>${same.map(x=>`<tr><td>${esc(x[0])}</td><td>${esc(x[2])}</td><td class="n">${f(x[3])}</td></tr>`).join('')}</table>`:''}`;
  document.getElementById('modal').style.display='flex'; }
function closeM(){ document.getElementById('modal').style.display='none'; } document.getElementById('modal').onclick=e=>{ if(e.target.id==='modal') closeM(); };
const kc={}; function keyset(n){ if(kc[n]) return kc[n]; return kc[n]=(n.match(/[A-Za-z0-9][A-Za-z0-9\-\/.+]*/g)||[]).map(t=>t.replace(/[^A-Za-z0-9]/g,'').toUpperCase()).filter(t=>t.length>=6&&/[A-Z]/.test(t)&&/\d/.test(t)); }
// ---------- derived fields (computed once) ----------
const VG=v=>!v?'(not a promo)':v.startsWith('REAL CUT')?'Real cut':v.startsWith('PRICE RAISED')?'Price raised':v.startsWith('FAKE')?'Fake discount':v.startsWith('No real')?'No real change':v.startsWith('BELOW')?'Below market low':v.startsWith('At market')?'At market low':v.startsWith('Above')?'Above market low':'Unverified';
const X=R.map((r,i)=>{ const h=r[C.hist]||[]; return {i, r, brand:(r[2].split(/\s+/)[0]||'').toUpperCase().replace(/[^A-Z0-9-]/g,''),
  claimed:r[4]>r[3]?1-r[3]/r[4]:0, real:r[5]?1-r[3]/r[5]:null, vg:VG(r[6]), xs:(r[10]&&r[10]<r[3])?r[10]:0,
  trend:h.length>1?h[h.length-1][1]/h[0][1]-1:null, low:(r[0]+' '+r[1]+' '+r[2]).toLowerCase()}; });
const uniq=a=>[...new Set(a)].filter(Boolean).sort((x,y)=>x.localeCompare(y));
const opt=(vals,sel,all)=>`<option value="">${all}</option>`+vals.map(v=>`<option ${v===sel?'selected':''}>${esc(v)}</option>`).join('');
// ---------- generic sortable table ----------
function cmp(a,b){ if(a==null||a==='') return 1; if(b==null||b==='') return -1; return typeof a==='number'&&typeof b==='number'?a-b:String(a).localeCompare(String(b)); }
function sortRows(rows,cols,st){ const c=cols.find(c=>c.k===st.sort)||cols[0]; return rows.slice().sort((a,b)=>{ const va=c.v(a), vb=c.v(b); if(va==null||va==='') return 1; if(vb==null||vb==='') return -1; return cmp(va,vb)*st.dir; }); }
function thead(cols,st,fn){ return '<tr>'+cols.map(c=>`<th class="${c.n?'n':''} ${c.hs?'hide-s':''}" onclick="${fn}('${c.k}')">${c.t}${st.sort===c.k?(st.dir>0?' ▲':' ▼'):''}</th>`).join('')+'</tr>'; }
function setSort(st,k,defDir){ if(st.sort===k) st.dir=-st.dir; else { st.sort=k; st.dir=defDir||1; } st.page=0; }
// ---------- Search tab ----------
const S={q:'',store:'',cat:'',brand:'',vg:'',min:'',max:'',dmin:'',onlyDisc:false,onlyXs:false,onlyReal:false,sort:'price',dir:1,page:0,per:100};
const SC=[
 {k:'store',t:'Store',v:x=>x.r[0]}, {k:'name',t:'Product',v:x=>x.r[2]}, {k:'price',t:'Price',n:1,v:x=>x.r[3]},
 {k:'old',t:'Crossed-out',n:1,hs:1,v:x=>x.r[4]||null}, {k:'claimed',t:'Claimed',n:1,v:x=>x.claimed||null},
 {k:'low',t:'30-day low',n:1,hs:1,v:x=>x.r[5]||null}, {k:'real',t:'vs 30-day low',n:1,v:x=>x.real},
 {k:'verdict',t:'Verdict',v:x=>x.r[6]||null}, {k:'xs',t:'Cheaper elsewhere',n:1,v:x=>x.xs||null}, {k:'trend',t:'Trend',n:1,hs:1,v:x=>x.trend}];
function search(){ const pool=X.filter(x=>!S.store||x.r[0]===S.store);
  main.innerHTML=`<div class="card filters">
  <input type="search" id="q" placeholder="Search model, brand or name… (e.g. OLED65C61LA, G20 Max, RTX 5070)" value="${esc(S.q)}">
  <select id="st">${opt(uniq(X.map(x=>x.r[0])),S.store,'All stores')}</select>
  <select id="ca">${opt(uniq(pool.map(x=>x.r[1].split(' · seller')[0])),S.cat,'All categories')}</select>
  <select id="br">${opt(uniq(pool.map(x=>x.brand)),S.brand,'All brands')}</select>
  <select id="vg">${opt(['Real cut','Fake discount','Price raised','No real change','Below market low','At market low','Above market low','Unverified','(not a promo)'],S.vg,'Any verdict')}</select>
  <input id="mn" type="number" placeholder="min RSD" value="${S.min}" style="width:105px"><input id="mx" type="number" placeholder="max RSD" value="${S.max}" style="width:105px">
  <input id="dm" type="number" placeholder="min claimed %" title="minimum claimed discount in %" value="${S.dmin}" style="width:125px">
  <label><input type="checkbox" id="od" ${S.onlyDisc?'checked':''}> discounted only</label>
  <label><input type="checkbox" id="or" ${S.onlyReal?'checked':''}> below its own 30-day low</label>
  <label><input type="checkbox" id="ox" ${S.onlyXs?'checked':''}> cheaper at another store</label>
  <select id="pp">${[50,100,250,500].map(n=>`<option ${n===S.per?'selected':''}>${n}</option>`).join('')}</select>
  <button id="rs">Reset</button></div>
  <div class="card"><div id="cnt" class="mut"></div><div class="wrap" id="tbl"></div><div class="pager" id="pg"></div></div>`;
  const upd=()=>{ const st0=S.store; Object.assign(S,{q:q.value,store:st.value,cat:ca.value,brand:br.value,vg:vg.value,min:mn.value,max:mx.value,dmin:dm.value,
     onlyDisc:od.checked,onlyReal:or.checked,onlyXs:ox.checked,per:+pp.value,page:0}); if(st0!==S.store){ S.cat=''; S.brand=''; search(); } else table(); };
  for(const id of ['st','ca','br','vg','mn','mx','dm','od','or','ox','pp']) document.getElementById(id).addEventListener('change',upd);
  let tmr; q.addEventListener('input',()=>{ clearTimeout(tmr); tmr=setTimeout(upd,200); });
  rs.onclick=()=>{ Object.assign(S,{q:'',store:'',cat:'',brand:'',vg:'',min:'',max:'',dmin:'',onlyDisc:false,onlyXs:false,onlyReal:false,page:0}); search(); };
  table(); }
function table(){ const w=S.q.toLowerCase().split(/\s+/).filter(Boolean);
  let rs=X.filter(x=>(!S.store||x.r[0]===S.store)&&(!S.cat||x.r[1].split(' · seller')[0]===S.cat)&&(!S.brand||x.brand===S.brand)&&(!S.vg||x.vg===S.vg)
    &&(!S.min||x.r[3]>=+S.min)&&(!S.max||x.r[3]<=+S.max)&&(!S.dmin||x.claimed*100>=+S.dmin)&&(!S.onlyDisc||x.claimed>0)&&(!S.onlyReal||(x.real!=null&&x.real>0))&&(!S.onlyXs||x.xs>0)
    &&w.every(t=>x.low.includes(t)));
  rs=sortRows(rs,SC,S); const pages=Math.max(1,Math.ceil(rs.length/S.per)); if(S.page>=pages) S.page=pages-1;
  cnt.textContent=`${rs.length.toLocaleString()} articles`;
  tbl.innerHTML=`<table>${thead(SC,S,'srt')}${rs.slice(S.page*S.per,(S.page+1)*S.per).map(x=>{ const r=x.r; return `<tr onclick="openItem(${x.i})" style="cursor:pointer">
   <td>${esc(r[0])}</td><td>${esc(r[2])}<div class="mut" style="font-size:12px">${esc(r[1])}</div></td><td class="n"><b>${f(r[3])}</b></td>
   <td class="n hide-s">${f(r[4])}</td><td class="n">${x.claimed?'−'+pct(x.claimed):''}</td><td class="n hide-s">${f(r[5])}</td>
   <td class="n">${x.real==null?'':x.real>0?'<span class="g">−'+pct(x.real)+'</span>':x.real<0?'<span class="b">+'+pct(-x.real)+'</span>':'0%'}</td>
   <td>${vpill(r[6])}</td><td class="n">${x.xs?`<span class="b">${f(x.xs)}</span><div class="mut" style="font-size:12px">${esc(r[11])}</div>`:''}</td>
   <td class="n hide-s">${spark(r[C.hist])}${x.trend?`<div class="mut" style="font-size:11px">${x.trend>0?'+':''}${(x.trend*100).toFixed(0)}%</div>`:''}</td></tr>`; }).join('')}</table>`;
  pg.innerHTML=pages>1?`<button ${S.page?'':'disabled'} onclick="S.page=0;table()">«</button><button ${S.page?'':'disabled'} onclick="S.page--;table()">‹ Prev</button><span class="mut">Page ${S.page+1} / ${pages}</span><button ${S.page<pages-1?'':'disabled'} onclick="S.page++;table()">Next ›</button><button ${S.page<pages-1?'':'disabled'} onclick="S.page=${pages-1};table()">»</button>`:''; }
function srt(k){ setSort(S,k,['price','name','store','xs'].includes(k)?1:-1); table(); }
// ---------- Deals tab (each list sortable + shared store/price filter) ----------
const DF={store:'',min:'',max:''};
const DL={both:{sort:'saved',dir:-1},real:{sort:'saved',dir:-1},raised:{sort:'real',dir:1},fake:{sort:'claimed',dir:-1}};
const DC=[{k:'store',t:'Store',v:x=>x.r[0]},{k:'name',t:'Product',v:x=>x.r[2]},{k:'price',t:'Price',n:1,v:x=>x.r[3]},{k:'old',t:'Crossed-out',n:1,v:x=>x.r[4]||null},
 {k:'claimed',t:'Claimed',n:1,v:x=>x.claimed||null},{k:'low',t:'30-day low',n:1,v:x=>x.r[5]||null},{k:'real',t:'vs 30-day low',n:1,v:x=>x.real},
 {k:'saved',t:'Saved (RSD)',n:1,v:x=>x.r[5]?x.r[5]-x.r[3]:null},{k:'market',t:'Market',v:x=>x.r[7]||null}];
function dlist(id,title,rs,note){ const st=DL[id]; rs=sortRows(rs,DC,st); const lim=400;
  return `<div class="card"><h3 style="margin-top:0">${title} <span class="mut">(${rs.length})</span></h3>${note?`<p class="mut">${note}</p>`:''}<div class="wrap"><table>${thead(DC,st,"dsrt.bind(null,'"+id+"')")}
  ${rs.length?'':'<tr><td colspan=9 class="mut">None.</td></tr>'}${rs.slice(0,lim).map(x=>{ const r=x.r; return `<tr onclick="openItem(${x.i})" style="cursor:pointer"><td>${esc(r[0])}</td><td>${esc(r[2])}</td><td class="n"><b>${f(r[3])}</b></td><td class="n">${f(r[4])}</td>
  <td class="n">${x.claimed?'−'+pct(x.claimed):''}</td><td class="n">${f(r[5])}</td><td class="n">${x.real==null?'':x.real>0?'<span class="g">−'+pct(x.real)+'</span>':'<span class="b">+'+pct(-x.real)+'</span>'}</td>
  <td class="n">${r[5]?f(r[5]-r[3]):''}</td><td>${vpill(r[7])}</td></tr>`; }).join('')}</table>${rs.length>lim?`<p class="mut">Showing first ${lim} – narrow with the filters above.</p>`:''}</div></div>`; }
function dsrt(id,k){ setSort(DL[id],k,['store','name','price'].includes(k)?1:-1); deals(); }
function deals(){ const base=X.filter(x=>(!DF.store||x.r[0]===DF.store)&&(!DF.min||x.r[3]>=+DF.min)&&(!DF.max||x.r[3]<=+DF.max));
  const real=base.filter(x=>x.vg==='Real cut'), both=real.filter(x=>/BUY-WORTHY|BEST IN MARKET/.test(x.r[7]));
  main.innerHTML=`<div class="card filters"><select id="dst">${opt(uniq(X.map(x=>x.r[0])),DF.store,'All stores')}</select>
   <input id="dmn" type="number" placeholder="min RSD" value="${DF.min}" style="width:105px"><input id="dmx" type="number" placeholder="max RSD" value="${DF.max}" style="width:105px"></div>`
   +dlist('both','Real deals – real cut AND cheapest in market',both)
   +dlist('real','Real cuts vs the store\'s own 30-day low',real)
   +dlist('raised','Price raised – "discount" above the store\'s own 30-day low',base.filter(x=>x.vg==='Price raised'))
   +dlist('fake','Fake discounts – price equals the 30-day low',base.filter(x=>x.vg==='Fake discount'));
  const u=()=>{ DF.store=dst.value; DF.min=dmn.value; DF.max=dmx.value; deals(); }; ['dst','dmn','dmx'].forEach(i=>document.getElementById(i).addEventListener('change',u)); }
// ---------- Price drops tab (sortable + filters) ----------
const PF={store:'',q:'',min:'',sort:'drop',dir:-1};
const PC=[{k:'store',t:'Store',v:d=>d[0]},{k:'name',t:'Product',v:d=>d[2]},{k:'before',t:'Before',n:1,v:d=>d[4]},{k:'now',t:'Now',n:1,v:d=>d[3]},
 {k:'drop',t:'Drop',n:1,v:d=>d[5]},{k:'rsd',t:'Drop (RSD)',n:1,v:d=>d[4]-d[3]},{k:'low',t:'Our 30-day low',n:1,v:d=>d[8]||null}];
function drops(){ const w=PF.q.toLowerCase().split(/\s+/).filter(Boolean);
  let rs=D.drops.filter(d=>(!PF.store||d[0]===PF.store)&&(!PF.min||d[5]*100>=+PF.min)&&w.every(t=>(d[0]+' '+d[2]).toLowerCase().includes(t))); rs=sortRows(rs,PC,PF);
  main.innerHTML=`<div class="card filters"><input type="search" id="pq" placeholder="Search…" value="${esc(PF.q)}"><select id="pst">${opt(uniq(D.drops.map(d=>d[0])),PF.store,'All stores')}</select>
   <input id="pmn" type="number" placeholder="min drop %" value="${PF.min}" style="width:115px"></div>
   <div class="card"><h3 style="margin-top:0">Price drops ≥3% since the previous run <span class="mut">(${rs.length})</span></h3><div class="wrap"><table>${thead(PC,PF,'psrt')}
  ${rs.map(d=>`<tr><td>${esc(d[0])}</td><td>${d[9]?`<a href="${esc(d[9])}" target="_blank">${esc(d[2])}</a>`:esc(d[2])}</td><td class="n">${f(d[4])}</td><td class="n"><b>${f(d[3])}</b></td><td class="n g">−${pct(d[5])}</td><td class="n">${f(d[4]-d[3])}</td><td class="n">${f(d[8])}</td></tr>`).join('')||'<tr><td colspan=7 class="mut">None.</td></tr>'}</table></div></div>`;
  const u=()=>{ PF.store=pst.value; PF.min=pmn.value; PF.q=pq.value; drops(); }; ['pst','pmn'].forEach(i=>document.getElementById(i).addEventListener('change',u));
  let t; pq.addEventListener('input',()=>{ clearTimeout(t); t=setTimeout(()=>{ u(); const e=document.getElementById('pq'); e.focus(); e.setSelectionRange(e.value.length,e.value.length); },300); }); }
function psrt(k){ setSort(PF,k,['store','name'].includes(k)?1:-1); drops(); }
function watch(){ const g={}; D.watch.forEach(w=>(g[w[0]]=g[w[0]]||[]).push(w));
  main.innerHTML=Object.entries(g).map(([k,ws])=>`<div class="card"><h3 style="margin-top:0">${esc(k)}</h3><div class="wrap"><table><tr><th>Store</th><th>Product</th><th>Specs</th><th class="n">Price</th><th class="n">30-day low</th><th class="n">Market best</th><th>Verdict</th></tr>
  ${ws.map(w=>`<tr><td>${esc(w[1])}</td><td>${w[12]?`<a href="${esc(w[12])}" target="_blank">${esc(w[2])}</a>`:esc(w[2])}</td><td>${esc(w[3])}</td><td class="n"><b>${f(w[4])}</b></td><td class="n">${f(w[6])}</td><td class="n">${f(w[8])} <span class="mut">${esc(w[9])}</span></td><td>${vpill(String(w[11]))}</td></tr>`).join('')}</table></div></div>`).join('')||'<div class="card mut">No watch items in this run.</div>'; }
function stores(){ const cnt={}; R.forEach(r=>cnt[r[0]]=(cnt[r[0]]||0)+1);
  main.innerHTML=`<div class="kpis">${Object.entries(cnt).map(([s,n])=>`<div class="kpi"><span class="mut">${esc(s)}</span><b>${n.toLocaleString()}</b><span class="mut">articles</span></div>`).join('')}</div>
  <div class="card" style="margin-top:14px"><table><tr><th>Store</th><th class="n">Promos ≥15k</th><th class="n">Avg claimed</th><th class="n">With 30-day low</th><th class="n">Real cuts</th><th class="n">Fake</th><th class="n">Raised</th><th class="n">Avg real</th></tr>
  ${D.summary.map(s=>`<tr><td>${esc(s[0])}</td><td class="n">${s[1]}</td><td class="n">${s[2]!==''?pct(s[2]):''}</td><td class="n">${s[3]}</td><td class="n g">${s[4]}</td><td class="n">${s[5]}</td><td class="n b">${s[6]}</td><td class="n">${s[7]!==''?pct(s[7]):''}</td></tr>`).join('')}</table></div>`; }
function report(){ main.innerHTML=`<div class="card"><pre>${esc(D.report||'No report text in this run.')}</pre></div>`; }
const T={search,deals,drops,watch,stores,report};
nav.onclick=e=>{ const t=e.target.dataset.t; if(!t) return; [...nav.children].forEach(b=>b.classList.toggle('on',b===e.target)); T[t](); };
search();
</script></body></html>"""

if __name__ == "__main__":
    runs = sorted((HERE / "runs").glob("20*"))
    if not runs: raise SystemExit("no runs yet")
    print(build(runs[-1], runs[-1].name))
