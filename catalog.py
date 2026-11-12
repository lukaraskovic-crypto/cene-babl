"""
Full-catalogue crawlers (every article, not only Black Friday) + local price history.

Each crawler runs inside the shop's own origin in Chromium (in-page fetch), returns a list of
dicts: {store, cat, name, p (price), o (crossed-out/list price or None), l (store's own 30-day low or None), u (url)}.
The 30-day low is only fetched from product pages for articles that show a discount (o > p),
because only those need the legal check – this keeps the run to a few hours.
"""
import re, sqlite3, time, json, datetime as dt
from pathlib import Path

# ------------------------------------------------------------------ JS helpers (on top of JS_COMMON)
JS_CAT = r"""
window.sameOrigin = h => { try{ const u=new URL(h, location.origin); return u.origin===location.origin ? u : null; }catch(e){ return null; } };
window.linksOf = (html, re) => { const d=new DOMParser().parseFromString(html,'text/html'); const out=new Set();
  d.querySelectorAll('a[href]').forEach(a=>{ const u=sameOrigin(a.getAttribute('href')); if(u && re.test(u.pathname)) out.add(u.pathname.replace(/\/$/,'')); });
  return [...out]; };
window.locs = xml => [...xml.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/g)].map(m=>m[1]);
// generic: find VTEX-like product objects anywhere in a JSON tree
window.vtexProducts = (root) => { const out=[]; const seen=new Set();
  const walk = (o, depth) => { if(!o || depth>12) return;
    if(Array.isArray(o)){ o.forEach(x=>walk(x,depth+1)); return; }
    if(typeof o!=='object') return;
    const name = o.productName || (o.items && o.name);
    if(name && (o.items || o.priceRange || o.linkText || o.link)){
      let p=null, lp=null;
      try{ const co=o.items[0].sellers.find(s=>s.sellerDefault||true).commertialOffer;
           if(co.Price!=null){ p=co.Price; lp=co.ListPrice; } else { p=co.ListPrice; lp=null; } }catch(e){}
      let navOld=null, navHist=null;
      (o.properties||[]).forEach(pr=>{ const v=parseFloat((pr.values||[])[0]); if(pr.name==='NAV Retail Price') navOld=v; if(pr.name==='NAV Price History') navHist=v; });
      // Gigatron's "NAV Retail Price" is a blanket reference price (~+16% on every article), not a real promotion,
      // so it is NOT used as a crossed-out price here; real promos come from the ?akcije=1 crawl.
      if(p==null && o.priceRange){ p=o.priceRange.sellingPrice && (o.priceRange.sellingPrice.lowPrice ?? o.priceRange.sellingPrice.highPrice);
                                   lp=o.priceRange.listPrice && (o.priceRange.listPrice.highPrice ?? o.priceRange.listPrice.lowPrice); }
      let link = o.link || (o.linkText ? '/proizvod/'+o.linkText : '');
      try{ link=new URL(link, location.origin).pathname; }catch(e){}
      const key=link||name; if(!seen.has(key)){ seen.add(key);
        const cats=(o.categories&&o.categories[0])||''; out.push({n:String(name).trim(), u:location.origin+link, p:p?Math.round(p):null,
          o:(lp&&p&&lp>p)?Math.round(lp):null, hist:navHist?Math.round(navHist):null, cat:String(cats).split('/').filter(Boolean).pop()||''}); }
      return; }
    for(const k in o) walk(o[k], depth+1); };
  walk(root,0); return out; };
"""

FULL_MINUTES = 60   # time limit for one store's full-catalogue crawl (config: full_store_minutes)
JS_SEL = r'''
// category selection (categories.json "exclude": path prefixes) + leaves-only + cached 30-day lows
window.notExcluded = (p, ex) => !ex.some(e => p === e || p.startsWith(e + '/'));
window.leavesOf = cats => cats.filter(c => !cats.some(d => d !== c && d.startsWith(c + '/')));
window.lowsWithCache = async (disc, known, re) => {
  const todo = [];
  for (const x of disc) { const k = known[x.u]; if (k && k[0] === x.p) { x.l = k[1]; x.lc = 1; } else todo.push(x); }
  console.log('PROG ' + location.host + ' 30-day lows: ' + (disc.length - todo.length) + ' from cache, ' + todo.length + ' to fetch');
  await pool(todo, 4, async x => { const t = await ft2(x.u); x.l = t ? lowFrom(t, re) : null; x.lf = 1; }, 150);
};
true;   // (Playwright would call a function left as the last value)
'''

def _run(br, code, arg=None):
    br.page.evaluate(JS_CAT); br.page.evaluate(JS_SEL)
    br.page.evaluate("m => { window.__deadline = Date.now() + m*60000; window.__dlHit = 0; }", FULL_MINUTES)
    return br.js(code, arg)

def _catinfo(res):
    """{path: articles listed} for every discovered category (0 = excluded / not crawled)."""
    cnt = res.get("cnt") or {}
    return {p: cnt.get(p, 0) for p in (res.get("allCats") or [])} | cnt

# ------------------------------------------------------------------ Gigatron (VTEX headless, Next.js)
def full_gigatron(br, log, max_pages=60, exclude=(), known=None):
    br.go("https://gigatron.rs")
    res = _run(br, r"""async ([maxPages, ex, known])=>{
      const fails=[]; let cats=[];
      const idx=await ft2('/sitemap_index.xml');
      const sm=(idx?locs(idx):[]).find(u=>/kategorije/.test(u));
      if(sm){ const x=await ft2(new URL(sm).pathname); if(x) cats=locs(x).map(u=>new URL(u).pathname.replace(/\/$/,'')); }
      if(!cats.length) fails.push('no category sitemap');
      // keep leaf-ish categories (2-3 levels) to stay under the 50-page search cap
      cats=[...new Set(cats.filter(p=>p.split('/').filter(Boolean).length>=2))];
      const allCats=cats.slice(); cats=leavesOf(cats).filter(p=>notExcluded(p,ex));
      const items={}; let apiOK=0, apiFail=0; const cnt={};
      await pool(cats,4,async path=>{
        const segs=path.split('/').filter(Boolean); const facets=segs.map((s,i)=>'category-'+(i+1)+'/'+s).join('/');
        for(let pg=1; pg<=maxPages; pg++){
          if(window.__deadline && Date.now()>window.__deadline) break;
          const t=await ft2('/api/vtex/plp-search?facetsPath='+encodeURIComponent(facets)+'&page='+pg);
          let arr=null; if(t){ try{ arr=vtexProducts(JSON.parse(t)); apiOK++; }catch(e){ apiFail++; } }
          if(arr===null){ // fallback: server-rendered first page
            if(pg===1){ const h=await ft2(path); if(h) parseGiga(h).forEach(x=>{ if(!items[x.u]) items[x.u]={...x,cat:segs[segs.length-1]}; }); }
            break; }
          cnt[path]=(cnt[path]||0)+arr.length;
          let added=0; arr.forEach(x=>{ if(x.p && !items[x.u]){ items[x.u]={...x,cat:x.cat||segs[segs.length-1],cp:path}; added++; } });
          if(!added) break; await sleep(200); }
      },300);
      // 30-day low only for discounted articles
      const disc=Object.values(items).filter(x=>x.o && x.o>x.p).sort((a,b)=>((b.p>=15000)-(a.p>=15000)) || ((1-b.p/b.o)-(1-a.p/a.o)));  // most relevant first, in case the time limit cuts in
      await lowsWithCache(disc, known, /Najni[žz]a cena u proteklih 30 dana\s*([\d.]+)/i);
      return {items:Object.values(items), fails, cats:cats.length, apiOK, apiFail, cnt, allCats}; }""", [max_pages, list(exclude), known or {}])
    log(f"Gigatron full: {len(res['items'])} articles from {res['cats']} categories (api ok {res['apiOK']}, api fail {res['apiFail']})")
    return [dict(store="Gigatron", **x) for x in res["items"]], [f"Gigatron {f}" for f in res["fails"]], _catinfo(res)

# ------------------------------------------------------------------ Magento (WinWin, Tehnomanija)
MAG_TOP = r"^/(bela-tehnika|it-gaming|klime-grejanje-i-kvalitet-vazduha|mali-kucni-aparati|telefoni-smart-satovi-i-tableti|tv-foto-audio-i-video|sudomasine)(/[a-z0-9-]+){0,3}$"

def full_magento(br, store, home, log, max_pages=80, exclude=(), known=None):
    br.go(home)
    res = _run(br, r"""async ([top,maxPages,ex,known])=>{
      const re=new RegExp(top); const fails=[];
      const h=await ft2('/'); let cats=h?linksOf(h,re):[];
      // second level discovery from each top category page
      const tops=[...new Set(cats.map(p=>'/'+p.split('/')[1]))];
      for(const t of tops){ const x=await ft2(t); if(x) linksOf(x,re).forEach(p=>cats.push(p)); await sleep(200); }
      cats=[...new Set(cats)];
      const allCats=cats.slice(); cats=leavesOf(cats).filter(p=>notExcluded(p,ex));   // leaves only: no page is fetched twice, and excluding a subcategory really excludes it
      const items={}; const visited=[]; const cnt={};
      await pool(cats,4,async c=>{ for(let p=1;p<=maxPages;p++){ const t=await ft2(c+'?product_list_limit=60&p='+p);
          if(!t){ fails.push(c+' p'+p); break; } const arr=parseMag(t); if(!arr.length) break;
          cnt[c]=(cnt[c]||0)+arr.length;
          let added=0; arr.forEach(x=>{ if(x.u && x.p && !items[x.u]){ x.cat=c.split('/').pop(); x.cp=c; items[x.u]=x; added++; } });
          if(!added) break; await sleep(200);} visited.push(c); },300);
      const disc=Object.values(items).filter(x=>x.o && x.o>x.p).sort((a,b)=>((b.p>=15000)-(a.p>=15000)) || ((1-b.p/b.o)-(1-a.p/a.o)));  // most relevant first, in case the time limit cuts in
      await lowsWithCache(disc, known, /Najni[žz]a web cena u prethodnih 30 dana\s*:?\s*([\d.]+)/i);
      return {items:Object.values(items), fails:fails.slice(0,20), cats:cats.length, cnt, allCats}; }""", [MAG_TOP, max_pages, list(exclude), known or {}])
    log(f"{store} full: {len(res['items'])} articles from {res['cats']} categories")
    return [dict(store=store, **x) for x in res["items"]], [f"{store} {f}" for f in res["fails"]], _catinfo(res)

# ------------------------------------------------------------------ Big Bang
BB_SKIP = r"^/(prijava|signup|kontakt|poslovnice|textovi|outlet|promocije|proizvodi-|korpa|cart|lista-zelja|search|pretraga|nalog|blog|brend|brands)"
BB_ELECTRO = r"(televiz|projekt|audio|zvucn|video|tv-|laptop|tablet|racunar|monitor|bela-tehnika|frizider|ves-mas|sporet|sudov|susenje|zamrziv|aspirat|bojler|ugradn|mikrotalas|vitrin|klima|grejan|radijator|usisiv|aparati-za-kafu|kafe|mobilni|telefon|satov|gaming|konzol|kamer|foto|dron|stampac|mali-kucni|kuhinjsk|friteze|preciscivac|ovlazivac|odvlazivac|pegl|blender|mikser|soundbar|slusalic)"

def full_bigbang(br, log, max_pages=40, exclude=(), known=None):
    br.go("https://www.bigbang.rs")
    res = _run(br, r"""async ([skip,electro,maxPages,ex])=>{
      const sk=new RegExp(skip), el=new RegExp(electro); const fails=[];
      const h=await ft2('/'); let cats=h?linksOf(h,/^\/[a-z0-9.-]+$/):[];
      cats=[...new Set(cats.filter(p=>!sk.test(p) && el.test(p)))];
      const allCats=cats.slice(); cats=cats.filter(p=>notExcluded(p,ex));
      const items={}; const cnt={};
      await pool(cats,4,async c=>{
        // try ?page=N; if page 2 adds nothing on a full first page, try ?p=N instead
        for(const param of ['page','p']){ let added2=0;
          for(let p=1;p<=maxPages;p++){ const t=await ft2(c+'?'+param+'='+p);
            if(!t){ fails.push(c); break; } const arr=parseBB(t); let added=0; cnt[c]=(cnt[c]||0)+arr.length;
            arr.forEach(x=>{ if(x.id && x.p && !items[x.id]){ items[x.id]={n:x.n, u:location.origin+c, p:Math.round(x.p), o:x.d>0?Math.round(x.p+x.d):null, l:null, cat:x.c||c.slice(1), cp:c}; added++; } });
            if(p===2) added2=added; if(!added) break; await sleep(200); }
          if(added2>0) break; }
      },300);
      return {items:Object.values(items), fails:fails.slice(0,20), cats:cats.length, cnt, allCats}; }""", [BB_SKIP, BB_ELECTRO, max_pages, list(exclude)])
    log(f"Big Bang full: {len(res['items'])} articles from {res['cats']} category pages")
    return [dict(store="Big Bang", **x) for x in res["items"]], [f"Big Bang {f}" for f in res["fails"]], _catinfo(res)

# ------------------------------------------------------------------ Ananas (marketplace)
AN_TOP = ["tv-audio-i-video", "it-shop", "telefoni-i-foto", "bela-tehnika", "mali-kucni-aparati", "gaming"]

def full_ananas(br, log, max_pages=30, exclude=(), known=None):
    br.go("https://ananas.rs")
    res = _run(br, r"""async ([tops,maxPages,ex])=>{
      const fails=[]; let cats=[];
      for(const t of tops){ const base='/kategorije/'+t; const h=await ft2(base); cats.push(base);
        if(h) linksOf(h,new RegExp('^'+base+'/[a-z0-9-]+(/[a-z0-9-]+)?$')).forEach(p=>cats.push(p)); await sleep(300); }
      cats=[...new Set(cats)];
      // prefer leaves: drop a category if a deeper one under it exists
      const allCats=leavesOf(cats); const leaves=allCats.filter(p=>notExcluded(p,ex));
      const items={}; const cnt={};
      await pool(leaves,4,async c=>{ const cat=c.split('/').pop(); for(let n=1;n<=maxPages;n++){ const t=await ft2(c+'?page='+n);
          if(!t){ fails.push(c+' p'+n); break; } let added=0; const arr=parseAn(t); cnt[c]=(cnt[c]||0)+arr.length;
          arr.forEach(x=>{ if(!items[x.id]){ x.cat=cat+' · seller '+x.s; x.cp=c; items[x.id]=x; added++; } });
          if(!added) break; await sleep(300);} },300);
      return {items:Object.values(items), fails:fails.slice(0,20), cats:leaves.length, cnt, allCats}; }""", [AN_TOP, max_pages, list(exclude)])
    log(f"Ananas full: {len(res['items'])} listings from {res['cats']} leaf categories")
    return [dict(store="Ananas", cat=x["cat"], cp=x.get("cp", ""), n=x["n"], u=x["u"], p=x["p"], o=x.get("o"), l=x.get("l")) for x in res["items"] if x.get("p")], \
           [f"Ananas {f}" for f in res["fails"]], _catinfo(res)

# ------------------------------------------------------------------ local price history (SQLite)
class History:
    """Price history that stores a row only when an article's price/crossed-out/30-day-low changes
    (keeps the file small enough to carry between cloud runs). Migrates the older one-row-per-day table."""
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.execute("""CREATE TABLE IF NOT EXISTS points(store TEXT, url TEXT, name TEXT, date TEXT, price INTEGER,
                           old INTEGER, low30 INTEGER, PRIMARY KEY(store, url, name, date))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS seen(store TEXT, url TEXT, name TEXT, first TEXT, last TEXT,
                           PRIMARY KEY(store, url, name))""")
        if self.db.execute("SELECT name FROM sqlite_master WHERE name='prices'").fetchone():
            rows = self.db.execute("SELECT date, store, url, name, price, old, low30 FROM prices ORDER BY store, url, name, date").fetchall()
            self._ingest(rows); self.db.execute("DROP TABLE prices"); self.db.commit(); self.db.execute("VACUUM")
        self._last = {}
        for s_, u, n, d, p, o, l in self.db.execute("""SELECT p.store,p.url,p.name,p.date,p.price,p.old,p.low30 FROM points p
                 JOIN (SELECT store,url,name,MAX(date) md FROM points GROUP BY store,url,name) m
                 ON p.store=m.store AND p.url=m.url AND p.name=m.name AND p.date=m.md"""):
            self._last[(s_, u, n)] = (d, p, o, l)
    def _ingest(self, rows):
        last = {}
        for d, s_, u, n, p, o, l in rows:
            k = (s_, u, n)
            if last.get(k) != (p, o, l):
                self.db.execute("INSERT OR REPLACE INTO points VALUES(?,?,?,?,?,?,?)", (s_, u, n, d, p, o, l)); last[k] = (p, o, l)
            self.db.execute("""INSERT INTO seen VALUES(?,?,?,?,?) ON CONFLICT(store,url,name) DO UPDATE SET
                               first=MIN(first,excluded.first), last=MAX(last,excluded.last)""", (s_, u, n, d, d))
    def save(self, date, items):
        for i in items:
            k = (i["store"], i.get("u", ""), i["name"]); v = (i["p"], i.get("o"), i.get("l"))
            prev = self._last.get(k)
            if prev is None or prev[1:] != v or prev[0] == date:
                self.db.execute("INSERT OR REPLACE INTO points VALUES(?,?,?,?,?,?,?)", (*k, date, *v)); self._last[k] = (date, *v)
            self.db.execute("""INSERT INTO seen VALUES(?,?,?,?,?) ON CONFLICT(store,url,name) DO UPDATE SET
                               last=MAX(last,excluded.last), first=MIN(first,excluded.first)""", (*k, date, date))
        self.db.commit()
    def observed(self, date, store, url, name, days=30):
        """(lowest price in the previous `days` days excluding today, last price before today, days of history)."""
        start = (dt.date.fromisoformat(date) - dt.timedelta(days=days)).isoformat()
        k = (store, url, name)
        r = self.db.execute("SELECT first FROM seen WHERE store=? AND url=? AND name=?", k).fetchone()
        if not r or r[0] >= date: return None, None, 0
        inwin = self.db.execute("SELECT MIN(price) FROM points WHERE store=? AND url=? AND name=? AND date>=? AND date<?", (*k, start, date)).fetchone()[0]
        before = self.db.execute("SELECT price FROM points WHERE store=? AND url=? AND name=? AND date<? ORDER BY date DESC LIMIT 1", (*k, start)).fetchone()
        last = self.db.execute("SELECT price FROM points WHERE store=? AND url=? AND name=? AND date<? ORDER BY date DESC LIMIT 1", (*k, date)).fetchone()
        cands = [x for x in [inwin, before[0] if before else None] if x is not None]
        ndays = (dt.date.fromisoformat(date) - dt.date.fromisoformat(max(r[0], start))).days
        return (min(cands) if cands else None), (last[0] if last else None), ndays
    def meta(self):
        """{store|url|name: [price-since date, last-seen date]} – 'price since' = date of the last price change."""
        seen = {f"{s_}|{u}|{n}": l for s_, u, n, l in self.db.execute("SELECT store,url,name,last FROM seen")}
        return {f"{s_}|{u}|{n}": [d, seen.get(f"{s_}|{u}|{n}", d)] for (s_, u, n), (d, p, o, l) in self._last.items()}
    def series(self, days=120):
        """{store|url|name: [[MM-DD, price], ...]} – change points plus today's value."""
        start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        out = {}
        for s_, u, n, d, p in self.db.execute("SELECT store,url,name,date,price FROM points WHERE date>=? ORDER BY date", (start,)):
            out.setdefault(f"{s_}|{u}|{n}", []).append([d[5:], p])
        for (s_, u, n), (d, p, o, l) in self._last.items():
            k = f"{s_}|{u}|{n}"
            if k in out: out[k].append([dt.date.today().isoformat()[5:], p])
        return out
