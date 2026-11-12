#!/usr/bin/env python3
"""
Black Friday store-promotions checker (Belgrade) – standalone, no Claude needed.

What it does (same rules as the Claude routine):
  1. Crawls promoted items at Gigatron, WinWin, Tehnomanija, Big Bang, Ananas (+ Emmezeta status)
     in a real Chromium (Playwright), using in-page fetch() on each shop's own origin.
  2. Verdict vs the store's own legally required "lowest price in last 30 days".
  3. Compares every promo item with all competitors on pametno.rs (rate-limited, ~2 h).
  4. Watch groups: Xiaomi G20 Max, tablets with SIM, design/architecture laptops.
  5. Rewrites the DAILY REPORT sheet, appends to the PRICE HISTORY sheet,
     writes a text report and sends a notification (macOS + optional ntfy.sh push to phone).

Run:  python3 bf_watch.py            (full run)
      python3 bf_watch.py --no-pametno   (skip the 2-hour market check)
      python3 bf_watch.py --dry-run      (no Google Sheets writes)
"""
import argparse, json, os, re, statistics, subprocess, sys, time, datetime as dt
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
# cloud (GitHub Actions) overrides – secrets arrive as environment variables
if os.environ.get("GOOGLE_SA_JSON"):
    (HERE / "service_account.json").write_text(os.environ["GOOGLE_SA_JSON"], encoding="utf-8"); CFG["service_account_json"] = "service_account.json"
if os.environ.get("NTFY_TOPIC"): CFG["ntfy_topic"] = os.environ["NTFY_TOPIC"]
if os.environ.get("SITE_URL"): CFG["site_url"] = os.environ["SITE_URL"]
TZ = ZoneInfo("Europe/Belgrade")
TODAY = dt.datetime.now(TZ).date().isoformat()
OUT = HERE / "runs" / TODAY
OUT.mkdir(parents=True, exist_ok=True)
MIN_PRICE = CFG.get("min_price", 15000)

def log(*a):
    msg = " ".join(str(x) for x in a)
    print(time.strftime("%H:%M:%S"), msg, flush=True)
    with open(OUT / "run.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")

def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

def load(name):
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

# --------------------------------------------------------------------------------------
# In-page JavaScript helpers (injected into each shop's origin)
# --------------------------------------------------------------------------------------
JS_COMMON = r"""
window.toN = s => +String(s).replace(/\s/g,'').replace(/,\d{1,2}$/,'').replace(/\./g,'');
window.sleep = ms => new Promise(r=>setTimeout(r,ms));
window.ft = async (u,ms=30000) => { const c=new AbortController(); const tm=setTimeout(()=>c.abort(),ms);
  try { const r=await fetch(u,{signal:c.signal}); window.__lastUrl=r.url; window.__st=r.status; return await r.text(); }
  finally { clearTimeout(tm); } };
window.ft2 = async (u) => { for (let k=0;k<2;k++){ try { return await ft(u); } catch(e){ await sleep(2000); } } return null; };
window.lowFrom = (t,re) => { const m=t.replace(/<[^>]+>/g,' ').replace(/&nbsp;/g,' ').replace(/\s+/g,' ').match(re); return m?toN(m[1]):null; };
window.pool = async (arr, n, fn, pause=250) => { let i=0, done=0, last=Date.now(); const out=new Array(arr.length);
  await Promise.all([...Array(n)].map(async()=>{ while(i<arr.length){ if(window.__deadline && Date.now()>window.__deadline){ if(!window.__dlHit){ window.__dlHit=1; console.log('PROG '+location.host+' time limit reached at '+done+'/'+arr.length+', keeping what we have'); } break; } const k=i++; try{ out[k]=await fn(arr[k],k);}catch(e){ out[k]=null; } done++;
    if(Date.now()-last>120000){ last=Date.now(); console.log('PROG '+location.host+' '+done+'/'+arr.length); } await sleep(pause);} })); return out; };

window.parseGiga = function(html){
 const doc = new DOMParser().parseFromString(html,'text/html');
 const norm = h => { try{ return new URL(h, location.origin).pathname.replace(/\/$/,''); }catch(e){return h} };
 const byHref = {};
 for(const a of doc.querySelectorAll('a[href*="/proizvod/"]')){ const h=norm(a.getAttribute('href')); (byHref[h]=byHref[h]||[]).push(a); }
 const out=[];
 for(const h in byHref){
   const cands=[];
   for(const a of byHref[h]){ let el=a, best=null;
     while(el.parentElement && el.parentElement!==doc.body){ const p=el.parentElement;
       const hs=new Set([...p.querySelectorAll('a[href*="/proizvod/"]')].map(x=>norm(x.getAttribute('href'))));
       if(hs.size!==1) break; el=p; if(/RSD/.test(el.textContent)) best=el; }
     if(best) cands.push(best); }
   if(!cands.length) continue;
   const card = cands.find(c=>/Najni/.test(c.textContent)) || cands[0];
   const name = byHref[h].map(a=>a.textContent.trim()).sort((a,b)=>b.length-a.length)[0].replace(/\s+/g,' ');
   const ps=[...card.querySelectorAll('p')].filter(p=>/RSD/.test(p.textContent) && !/Ušteda|Najni|cena\s/i.test(p.textContent));
   const pe = card.querySelector('[itemprop="price"]');
   const price = pe? toN(pe.textContent.replace('RSD','')) : (ps.length? toN(ps[ps.length-1].textContent.replace('RSD','')):null);
   const others = ps.filter(p=>p!==pe).map(p=>toN(p.textContent.replace('RSD','')));
   const old = others.length? Math.max(...others) : null;
   const lowM = card.textContent.match(/Najni[žz]a cena u proteklih 30 dana\s*([\d.]+)/i);
   out.push({u:location.origin+h, n:name, p:price, o:old&&old>price?old:null, l:lowM?toN(lowM[1]):null});
 }
 return out;
};
window.parseMag = function(html){ const d=new DOMParser().parseFromString(html,'text/html');
 return [...d.querySelectorAll('li.product-item')].map(li=>{ const a=li.querySelector('a.product-item-link');
  const fp=li.querySelector('[data-price-type="finalPrice"]'), op=li.querySelector('[data-price-type="oldPrice"]');
  let p=fp?+fp.getAttribute('data-price-amount'):null, o=op?+op.getAttribute('data-price-amount'):null;
  if(p&&o&&p>o){const t=p;p=o;o=t;} if(o&&o<=p) o=null;
  return {n:a?a.textContent.trim().replace(/\s+/g,' '):'', u:a?new URL(a.getAttribute('href'),location.origin).href:'', p, o}; }); };
window.parseBB = t => { const out=[]; const parts=t.split(/\{\s*\\?"?item_id\\?"?\s*:/);
 for(let i=1;i<parts.length;i++){ const b=parts[i].slice(0,1500);
  const g=k=>{ const m=b.match(new RegExp('\\\\?"?'+k+'\\\\?"?\\s*:\\s*\\\\?["\']?([^"\',}\\\\]*)')); return m?m[1].trim():null; };
  out.push({id:(b.match(/^\s*\\?["']?([^"',\\]+)/)||[])[1], n:(g('item_name')||'').replace(/\\u0026/g,'&'), c:g('item_category2'), p:+g('price'), d:+(g('discount')||0)}); }
 return out; };
window.parseAn = html => { const d=new DOMParser().parseFromString(html,'text/html'); const out=[];
 for(const h2 of d.querySelectorAll('h2')){ let el=h2, card=null;
  while(el.parentElement&&el.parentElement!==d.body){ const p=el.parentElement; if(p.querySelectorAll('h2').length!==1) break; el=p; card=el; }
  if(!card) continue; const a=card.querySelector('a[href*="/proizvod/"]'); if(!a) continue;
  const sel=card.querySelector('p'); const old=card.querySelector('span.line-through,[class*="line-through"]');
  const pr=[...card.querySelectorAll('span')].find(s=>/text-lg/.test(s.className));
  const lm=card.textContent.match(/Najni[žz]a cena u prethodnih\s*30 dana\s*([\d.]+)/i); const href=a.getAttribute('href');
  out.push({n:h2.textContent.trim(), s:sel?sel.textContent.trim():'', u:location.origin+href, id:href.split('?')[0].split('/').filter(Boolean).pop(),
   o:old?toN((old.textContent.match(/[\d.]+(,\d+)?/)||[''])[0]):null, p:pr?toN((pr.textContent.match(/[\d.]+(,\d+)?/)||[''])[0]):null, l:lm?toN(lm[1]):null}); }
 return out; };
"""

GIGA_PATHS = ["/tv-audio-video/televizori", "/mobilni-telefoni-tableti-i-oprema/mobilni-telefoni",
 "/mobilni-telefoni-tableti-i-oprema/tablet-racunari", "/laptop-racunari-i-it-oprema/laptop-racunari",
 "/laptop-racunari-i-it-oprema/monitori", "/bela-tehnika/ves-masine/masine-za-pranje-vesa",
 "/bela-tehnika/ves-masine/masine-za-pranje-i-susenje-vesa", "/bela-tehnika/ves-masine/masine-za-susenje-vesa",
 "/bela-tehnika/frizideri/kombinovani-frizideri", "/bela-tehnika/masine-za-pranje-sudova/ugradne-sudomasine",
 "/bela-tehnika/klima-ure%C4%91aji-i-oprema/inverter-klime", "/mali-kucni-aparati/usisivaci", "/tv-audio-video/slusalice",
 "/mali-kuhinjski-aparati/espresso-i-kafe-aparati/espresso-aparati"]
MAG_KEEP = r"^/(bela-tehnika|it-gaming|klime-grejanje|mali-kucni-aparati|sudomasine|telefoni-smart|tv-foto-audio)"
BB_PAGES = ["/textovi/crni-petak-2026", "/textovi/audio-i-video-crni-petak-2026", "/textovi/bela-tehnika-crni-petak-2026",
 "/textovi/crni-petak-top-ponuda", "/textovi/grejanje-i-cist-vazduh-crni-petak-2026", "/textovi/mali-kucni-aparati-crni-petak-2026",
 "/textovi/tehnologija-na-dlanu-crni-petak-2026", "/textovi/televizori-crni-petak-2026"]
BB_SKIP_CATS = r"Brijaci|Depilatori|Epilatori|Fenovi|Prese za kosu|Styleri|Trimeri|Vage|Makaze|Vertikuleri|Agregati|Elektro materijal|Led trake|Gasni"
AN_PATHS = ["/kategorije/tv-audio-i-video/tv/televizori", "/kategorije/it-shop/racunari-i-racunarska-oprema/laptop-racunari",
 "/kategorije/telefoni-i-foto/mobilni-telefoni", "/kategorije/telefoni-i-foto/tableti", "/kategorije/bela-tehnika/ves-masine",
 "/kategorije/bela-tehnika/frizideri", "/kategorije/bela-tehnika/masine-za-pranje-sudova", "/kategorije/bela-tehnika/klima-uredjaji",
 "/kategorije/bela-tehnika/sporeti-rerne-i-ploce", "/kategorije/mali-kucni-aparati/usisivaci",
 "/kategorije/mali-kucni-aparati/aparati-za-kafu", "/kategorije/gaming/konzole"]
WATCH_TERMS = ["SM-X930 Galaxy Tab S11 Ultra 256GB", "LS27FG810", "PlayStation 5 Slim Digital", "PlayStation 5 Slim", "WGB24410BY",
 "65U8Q", "Galaxy S26+ 256GB", "OLED65C61LA", "OLED55G61LW", "OLED55C61LA", "XG27AQDMGR", "AW2725D", "OLED77C61LA", "QE65S99H",
 "OLED42C61LA", "QE65S90H", "iPhone 18 Pro Max 256GB", "iPhone 17 Pro 256GB", "Galaxy S26 256GB", "KGN49LBCF", "EP5547/90",
 "Nintendo Switch 2", "QE55LS03F", "SMS6ECC12E"]
G2_TERMS = ["tablet LTE", "tablet 5G", "Galaxy Tab 5G", "iPad Cellular"]
G3_TERMS = ["laptop 5060", "laptop 5070", "laptop 5080", "laptop 4060", "laptop 4070", "32/1TB/5060", "32/1TB/5070", "32/2TB", "MacBook Pro"]
SIM_RE = r"\b(LTE|4G|5G|Cellular|SIM)\b"

class Browser:
    def __init__(self, pw, headless):
        self.b = pw.chromium.launch(headless=headless)
        self.ctx = self.b.new_context(locale="sr-RS", user_agent=None)
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(120000)
        self.page.on("console", lambda m: log("  progress", m.text[5:]) if m.text.startswith("PROG ") else None)
    def go(self, url):
        for k in range(3):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=90000); break
            except Exception as e:
                log(f"open {url} failed (try {k+1}/3): {str(e).splitlines()[0]}")
                if k == 2: raise
                time.sleep(20)
        time.sleep(2)
        self.decline_cookies()
        self.page.evaluate(JS_COMMON)
    def decline_cookies(self):
        for txt in ["Odbij", "Odbij sve", "Samo neophodni", "Samo neophodne", "Decline", "Reject"]:
            try:
                b = self.page.get_by_role("button", name=re.compile(txt, re.I))
                if b.count():
                    b.first.click(timeout=2000); return
            except Exception:
                pass
    def js(self, code, arg=None):
        return self.page.evaluate(code, arg)
    def close(self):
        self.b.close()

# --------------------------------------------------------------------------------------
# PART 1 – store crawls
# --------------------------------------------------------------------------------------
def crawl_gigatron(br):
    br.go("https://gigatron.rs")
    items = br.js("""async (paths)=>{ const res=await pool(paths,4,async p=>{ const t=await ft2(p+'?akcije=1'); if(!t) return null;
        return parseGiga(t).map(x=>({...x,cat:p.split('/').pop()})); }); return res; }""", GIGA_PATHS)
    out, fails = [], []
    for p, r in zip(GIGA_PATHS, items):
        if r is None: fails.append(p)
        else: out += r
    return out, fails

def search_gigatron(br, terms):
    return br.js("""async (terms)=>{ const r=await pool(terms,4,async q=>{ const t=await ft2('/pretraga?q='+encodeURIComponent(q)); return t?parseGiga(t):null; }); return r; }""", terms)

def crawl_magento(br, home, bases):
    br.go(home)
    return br.js(r"""async ([bases,keep])=>{ const items={}; const fails=[];
      for(const base of bases){ for(let p=1;p<=80;p++){ const t=await ft2(base+(base.includes('?')?'&':'?')+'product_list_limit=60&p='+p);
         if(!t){fails.push(base+' p'+p); break;} let added=0; for(const x of parseMag(t)){ if(x.u&&!items[x.u]){items[x.u]=x; added++;} }
         if(!added) break; await sleep(250);} }
      const kre=new RegExp(keep); const kept=Object.values(items).filter(x=>{ let path=''; try{path=new URL(x.u).pathname}catch(e){} x.cat=path.split('/').slice(-2,-1)[0]; return kre.test(path)&&x.p>=15000&&x.o; });
      await pool(kept,4,async x=>{ const t=await ft2(x.u); x.l=t?lowFrom(t,/Najni[žz]a web cena u prethodnih 30 dana\s*:?\s*([\d.]+)/i):null; },200);
      return {items:kept, fails, total:Object.keys(items).length}; }""", [bases, MAG_KEEP])

def search_magento(br, terms):
    return br.js(r"""async (terms)=>{ const out={}; for(const q of terms){ try{ const t=await ft('/catalogsearch/result/?q='+encodeURIComponent(q)+'&product_list_limit=60');
        if(!/catalogsearch/.test(__lastUrl)){ const d=new DOMParser().parseFromString(t,'text/html'); const h=d.querySelector('h1');
          const fp=d.querySelector('.product-info-main [data-price-type="finalPrice"]'), op=d.querySelector('.product-info-main [data-price-type="oldPrice"]');
          let p=fp?+fp.getAttribute('data-price-amount'):null,o=op?+op.getAttribute('data-price-amount'):null; if(p&&o&&p>o){const z=p;p=o;o=z;}
          out[q]=[{n:h?h.textContent.trim():'',u:__lastUrl,p,o:o>p?o:null,l:lowFrom(t,/Najni[žz]a web cena u prethodnih 30 dana\s*:?\s*([\d.]+)/i)}]; }
        else out[q]=parseMag(t); }catch(e){ out[q]=null; } await sleep(400);} return out; }""", terms)

def magento_low(br, urls):
    return br.js(r"""async (us)=>pool(us,4,async u=>{ const t=await ft2(u); return t?lowFrom(t,/Najni[žz]a web cena u prethodnih 30 dana\s*:?\s*([\d.]+)/i):null; })""", urls)

def crawl_bigbang(br):
    br.go("https://www.bigbang.rs")
    return br.js("""async ([pages,skip])=>{ const items={}; const seen=new Set(pages); const fails=[]; let queue=[...pages];
      while(queue.length){ const batch=queue.splice(0,4); await Promise.all(batch.map(async p=>{ const t=await ft2(p); if(!t){fails.push(p);return;}
        parseBB(t).forEach(x=>{ if(x.id&&!items[x.id]) items[x.id]=x; });
        (t.match(/\\/textovi\\/[a-z0-9-]*(crni-petak|black-friday)[a-z0-9-]*/g)||[]).forEach(u=>{ if(!seen.has(u)&&!/lepota/.test(u)){seen.add(u); queue.push(u);} }); }));
        await sleep(300); }
      const sk=new RegExp(skip); return {items:Object.values(items).filter(x=>x.d>0&&x.p>=15000&&!sk.test(x.c||'')), fails, pages:seen.size}; }""", [BB_PAGES, BB_SKIP_CATS])

def search_bigbang(br, terms):
    return br.js("""async (terms)=>{ const out={}; for(const q of terms){ const t=await ft2('/search?q='+encodeURIComponent(q)); out[q]=t?parseBB(t):null; await sleep(400);} return out; }""", terms)

def crawl_ananas(br):
    br.go("https://ananas.rs")
    return br.js("""async (paths)=>{ let promos=[]; const t0=await ft2('/promo/crni-petak'); if(t0) promos=[...new Set(t0.match(/\\/promo\\/[a-z0-9-]*crni-petak[a-z0-9-]*/g)||[])];
      const all=[...paths,...promos]; const items={}; const fails=[];
      await pool(all,4,async p=>{ const cat=p.split('/').pop(); for(let n=1;n<=8;n++){ const t=await ft2(p+'?page='+n); if(!t){fails.push(p+' p'+n);break;}
         let added=0; parseAn(t).forEach(x=>{ if(!items[x.id]){x.cat=cat; items[x.id]=x; added++;} }); if(!added) break; await sleep(300);} },300);
      return {all:Object.values(items), fails}; }""", AN_PATHS)

def search_ananas(br, terms):
    return br.js("""async (terms)=>{ const out={}; for(const q of terms){ const t=await ft2('/pretraga?query='+encodeURIComponent(q)); out[q]=t?parseAn(t):null; await sleep(400);} return out; }""", terms)

def emmezeta_status(br):
    br.go("https://www.emmezeta.rs/akcijska-ponuda")
    txt = br.js("document.body.innerText")
    if re.search(r"\d[\d.]*,\d{2}\s*RSD|\d[\d.]+\s*RSD", txt or ""):
        return "Emmezeta /akcijska-ponuda shows priced items – check manually"
    return "Emmezeta /akcijska-ponuda shows only club-card category tiles (no itemised priced deals)"

# --------------------------------------------------------------------------------------
# PART 3 – pametno.rs
# --------------------------------------------------------------------------------------
JS_PAMETNO = r"""
async (terms) => {
 const sleep=ms=>new Promise(r=>setTimeout(r,ms)); const nz=s=>s.toLowerCase().replace(/[^a-z0-9]/g,'');
 window.__done=0; window.__err500=0;
 async function get(u){ for(let k=0;k<5;k++){ const c=new AbortController(); const tm=setTimeout(()=>c.abort(),30000);
   try{ const r=await fetch(u,{signal:c.signal}); clearTimeout(tm); if(r.status===500||r.status===429){ __err500++; await sleep(20000+Math.random()*20000); continue;} return await r.text(); }
   catch(e){ clearTimeout(tm); await sleep(8000);} } return null; }
 async function search(q){ const t=await get('/search.php?q='+encodeURIComponent(q)); await sleep(5500); if(t===null) return null;
   const d=new DOMParser().parseFromString(t,'text/html'); return [...new Set([...d.querySelectorAll('a[href]')].map(a=>a.getAttribute('href').split('?')[0]).filter(h=>/-\d{6,}$/.test(h)))]; }
 async function job(q){ let links=await search(q); if(links===null) return {e:'ERR'};
   if(!links.length){ const c=q.replace(/[^A-Za-z0-9]/g,''); if(!/\s/.test(q)&&c.length>9){ links=await search(q.slice(0,-3)); if(links===null) return {e:'ERR'}; } }
   if(!links.length) return {e:'NONE'};
   const qn=nz(q.split(' ').filter(w=>/\d/.test(w)).join('')||q); const pick=links.find(h=>nz(h).includes(qn))||links[0];
   const t=await get(pick); await sleep(5500); if(t===null) return {e:'ERR',u:pick};
   const d=new DOMParser().parseFromString(t,'text/html'); const best={};
   d.querySelectorAll('div.offer').forEach(o=>{ const lg=o.querySelector('.offer__store-logo');
     const st=((lg&&lg.getAttribute('alt'))||((o.querySelector('.offer__store')||{}).textContent)||'').trim().replace(/\s+\d(\.\d)?$/,'');
     const p=+(((o.querySelector('.offer__price')||{}).textContent||'').replace(/,\d+/,'').replace(/[^\d]/g,''));
     if(st&&p>0&&(!best[st]||p<best[st])) best[st]=p; });
   const arr=Object.entries(best).sort((a,b)=>a[1]-b[1]); const ps=arr.map(x=>x[1]);
   const med=ps.length?(ps.length%2?ps[(ps.length-1)/2]:(ps[ps.length/2-1]+ps[ps.length/2])/2):null;
   const m=pick.match(/^\/([^\/]+)\/(.*)-(\d+)$/)||['','','',''];
   return {u:'https://www.pametno.rs/'+m[1]+'/p-'+m[3], cat:m[1], slug:m[2], t:((d.querySelector('h1')||{}).textContent||'').trim().replace(/\s+/g,' '),
           n:arr.length, b:ps[0]||null, bs:arr[0]?arr[0][0]:'', s2:ps[1]||null, md:med, hi:ps[ps.length-1]||null,
           nx:arr.slice(1,3).map(x=>x[0]+' '+x[1]).join(', ')}; }
 const res=new Array(terms.length).fill(null); let next=0;
 await Promise.all([0,1].map(async w=>{ await sleep(w*2700); while(next<terms.length){ const i=next++; try{ res[i]=await job(terms[i]); }catch(e){ res[i]={e:'ERR'}; } __done++; } }));
 return res; }
"""

def run_pametno(br, terms, cache_name="pametno.json"):
    cache = load(cache_name) or {}
    todo = [t for t in terms if t not in cache or (cache[t] or {}).get("e") == "ERR"]
    log(f"pametno: {len(terms)} terms, {len(todo)} to fetch")
    br.go("https://www.pametno.rs")
    CH = 40   # chunks so progress is saved
    for k in range(0, len(todo), CH):
        part = todo[k:k + CH]
        try:
            res = br.js(JS_PAMETNO, part)
        except Exception as e:
            log("pametno chunk failed:", e); br.go("https://www.pametno.rs"); continue
        for t, r in zip(part, res): cache[t] = r
        save(cache_name, cache)
        log(f"pametno {min(k + CH, len(todo))}/{len(todo)}")
    return cache

# --------------------------------------------------------------------------------------
# Terms / matching / verdicts
# --------------------------------------------------------------------------------------
BRANDS = set("""SAMSUNG LG SONY PHILIPS HISENSE TCL GORENJE BOSCH BEKO CANDY HAIER VOX TESLA WHIRLPOOL INDESIT ELECTROLUX MIELE XIAOMI
APPLE ASUS LENOVO HP ACER MSI DELL GIGABYTE MOTOROLA HONOR HUAWEI DREAME ROBOROCK DYSON ROWENTA TEFAL DELONGHI KRUPS NESPRESSO MIDEA
GREE FOX UNION DIGITECH VIVAX JBL SONOS DJI INSTA360 GARMIN NINJA KARCHER AOC BENQ DOOGEE AMAZON LIEBHERR SAGE HEINNER GAGGIA ARZUM
OUKITEL STADLER ZEPTER DAIKIN EPSON EDIFIER LOGITECH BEATS IROBOT DIMPLEX NOBO BEHA TESY PROSTO VENTING ARIETE BERLINGER""".split())
JUNK = re.compile(r"^(\d+(GB|TB|MAH|W|L|BTU|KG|HZ|MM|CM|V|PA|K)|\d+GB/\d+(GB|TB)?|\d+/\d+(GB|TB)?|\d+X\d+|(I[3579]|U[579]|R[3579]|C[357])\d+[A-Z]*)$", re.I)
CATWORDS = re.compile(r"^(mašina|masina|za|pranje|sušenje|susenje|veša|vesa|kombinovani|frižider|frizider|ugradna|ugradni|sudove|sudova|inverter|klima|uređaj|uredjaj|espresso|espreso|aparat|kafu|usisivač|usisivac|štapni|stapni|robot|smart|televizor|tv|uhd|ultra|hd|4k|full|led|monitor|električni|elektricni|šporet|sporet|rerna|ploča|ploca|set|sivi|crni|beli|bela|crna|siva|grey|gray|black|white|silver|inox|i|sa|u|od|laptop|tablet|mobilni|telefon|enterprise|edition|wi-fi|wifi|zvučnik|zvucnik|bežični|dron|kamera|akciona|prečišćivač|odvlaživač|radijator|norveški|pegla|parna|stanica|friteza|blender|vazduha|qled|oled|uled|miniled|vision|ai)$", re.I)
nz = lambda s: re.sub(r"[^A-Za-z0-9]", "", s)

def term_for(name):
    codes = []
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.+]*", name):
        t = t.strip(".-/,"); t2 = nz(t)
        if len(t2) < 5 or not re.search(r"[A-Za-z]", t2) or not re.search(r"\d", t2): continue
        if JUNK.match(t2) or JUNK.match(t) or ("/" in t and re.search(r"GB|TB", t, re.I)): continue
        codes.append(t)
    if codes:
        b = max(codes, key=lambda t: len(nz(t)))
        if len(nz(b)) < 7:
            br = next((w.upper().strip(",") for w in name.split()[:3] if w.upper().strip(",") in BRANDS), name.split()[0].upper())
            return b if br in b.upper() else f"{br} {b}"
        return b
    words = [w for w in re.findall(r"[\w+]+", name) if not CATWORDS.match(w) and not re.fullmatch(r"\d+(/\d+)?(GB|TB)?", w, re.I) and len(w) > 1]
    return " ".join(words[:4])

VARS = ["PRO", "ULTRA", "PLUS", "+", "LITE", "MAX", "FE", "SLIM", "MINI", "EDGE", "STATION", "COMBO"]
def variants(s):
    s = s.upper()
    for x in ["ULTRA HD", "MINI LED", "MINILED", "MINI-LED", "QD-MINI"]: s = s.replace(x, "")
    v = set()
    for w in VARS:
        if w == "+":
            if re.search(r"\w\+(\s|$)", s): v.add("+")
        elif re.search(r"(?<![A-Z])" + w + r"(?![A-Z])", s): v.add(w)
    return v
def storage(s):
    return {a + b for a, b in re.findall(r"(\d+)\s*(GB|TB)", s.upper()) if not (b == "GB" and int(a) <= 24)}

def match_check(it, r):
    if r is None: return "NOT CHECKED"
    if r.get("e") == "NONE": return "NOT ON PAMETNO"
    if r.get("e"): return "LOOKUP FAILED"
    if not r["n"]: return "LISTED, NO CURRENT OFFERS"
    if variants(it["name"]) != variants(r["t"]): return "MODEL VARIANT DIFFERS"
    if re.search(r"telefon|tablet|laptop|racunar|iphone|galaxy|pad|macbook", it["cat"] + " " + it["name"], re.I):
        a, b = storage(it["name"]), storage(r["t"])
        if a and b and not (a & b): return "STORAGE DIFFERS"
    if re.search(r"oprema|baterij|dodatn|punjac|futrol|filter|zastitn|folij", r["cat"]) or re.match(r"(LCD|Baterija|Futrola|Maska|Staklo|Zaštitno|Punja|Zamenski)", r["t"], re.I):
        return "UNCERTAIN MATCH"
    if len(nz(it["term"])) < 8 and it["name"].split()[0].lower() not in (r["slug"] + r["t"]).lower(): return "UNCERTAIN MATCH"
    return "OK"

def market_verdict(P, r):
    B, M, n = r["b"], r["md"], r["n"]
    if n == 1: return "SINGLE SELLER"
    if P <= B * 1.01 and M and P <= M * 0.92 and n >= 3: return "BUY-WORTHY"
    if P < B * 0.99: return "BEST IN MARKET"
    if P <= B * 1.01: return "GOOD"
    if P <= B * 1.05: return "OK"
    return "SKIP"

def own_verdict(P, claimed, own30, mkt):
    if own30:
        real = 1 - P / own30
        if real >= 0.05:
            v = "REAL CUT"
            if mkt and P <= mkt * 1.01: v += " – best price in market"
            elif mkt and P > mkt * 1.03: v += " – but cheaper elsewhere"
            return v
        if P > own30 * 1.02: return "PRICE RAISED – above its own 30-day low"
        return "FAKE – no real cut" if claimed >= 0.10 else "No real change"
    if mkt is None: return "Unverified"
    if P <= mkt * 0.97: return "BELOW MARKET LOW"
    if P <= mkt * 1.01: return "At market low"
    return "Above market low"

def analyse(items, pm):
    for it in items:
        if not it.get("term"): it["term"] = term_for(it["name"])
        P = it["p"]
        it["claimed"] = round(1 - P / it["o"], 4) if it.get("o") else 0
        own = it.get("l")
        it["own_src"] = "store"
        if not own and it.get("l_obs") and it.get("obs_days", 0) >= CFG.get("min_history_days", 7):
            own = it["l_obs"]; it["own_src"] = "our record"
        it["l_used"] = own
        it["real"] = round(1 - P / own, 4) if own else None
        r = pm.get(it["term"])
        c = match_check(it, r)
        it["mcheck"] = c
        it["r"] = r if (r and not r.get("e")) else None
        if c == "OK":
            it["mkt"] = r["b"]; it["mv"] = market_verdict(P, r)
        elif it.get("xs"):          # no pametno result -> cheapest same model at the other crawled stores
            it["mkt"] = it["xs"]; it["mv"] = ("CROSS-STORE: cheapest of crawled stores" if P <= it["xs"] * 1.01
                                             else f"CROSS-STORE: cheaper at {it['xs_store']}")
        else:
            it["mkt"] = None; it["mv"] = c
        v = own_verdict(P, it["claimed"], own, it["mkt"])
        if own and it["own_src"] == "our record": v += " (vs our own 30-day record)"
        it["v"] = v
    return items

def code_keys(name):
    """Model-code tokens used to match the same article across stores."""
    out = set()
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.+]*", name):
        t2 = nz(t).upper()
        if len(t2) >= 6 and re.search(r"[A-Z]", t2) and re.search(r"\d", t2) and not JUNK.match(t2):
            out.add(t2)
    return out

def cross_store(all_items, items):
    """For each promo item: cheapest price of the same model code at a different crawled store."""
    idx = {}
    for a in all_items:
        for k in code_keys(a["name"]):
            idx.setdefault(k, []).append(a)
    for it in items:
        best = None
        for k in code_keys(it["name"]):
            for a in idx.get(k, []):
                if a["store"] == it["store"] or not a.get("p"): continue
                if variants(a["name"]) != variants(it["name"]): continue
                if a["p"] < it["p"] * 0.4: continue      # accessories / parts guard
                if best is None or a["p"] < best["p"]: best = a
        if best: it["xs"], it["xs_store"] = best["p"], best["store"]
    return items

# --------------------------------------------------------------------------------------
# Watch groups helpers
# --------------------------------------------------------------------------------------
def laptop_spec(name):
    n = name.replace(" ", "")
    ram = None
    m = re.search(r"/(\d{2,3})/(\d+(?:GB|TB))", name)
    if m: ram = int(m.group(1))
    else:
        m = re.search(r"(\d{2,3})\s*GB(?!\s*SSD)", name, re.I)
        if m: ram = int(m.group(1))
    gpu = None
    m = re.search(r"(?:RTX\s*|/)(40[6-9]0|50[6-9]0)(\s*Ti)?", name, re.I)
    if m: gpu = "RTX " + m.group(1) + (" Ti" if m.group(2) else "")
    mac = bool(re.search(r"MacBook Pro", name, re.I) and re.search(r"M[45]\s*(Pro|Max)", name, re.I))
    ssd = re.search(r"(\d)\s*TB", name, re.I)
    ok = (ram and ram >= 32 and gpu) or (mac and ram and ram >= 24) or (mac and re.search(r"M5\s*Max|M4\s*Max", name, re.I))
    chip = re.search(r"M[45]\s*(Pro|Max)", name, re.I)
    label = gpu or (("Apple " + chip.group(0)) if (mac and chip) else "?")
    return ok, f"{label} / {ram or '?'}GB / {(ssd.group(1) + 'TB') if ssd else '?'}"

def tablet_spec(name):
    ram = re.search(r"(\d{1,2})\s*(?:GB)?\s*/\s*(\d{2,4})\s*GB", name)
    sto = storage(name)
    sim = re.search(SIM_RE, name, re.I)
    return f"{sim.group(1) if sim else '?'} / {ram.group(1) + 'GB RAM' if ram else '?'} / {', '.join(sorted(sto)) or '?'}"

# --------------------------------------------------------------------------------------
# Google Sheets
# --------------------------------------------------------------------------------------
def sheets():
    import gspread
    gc = gspread.service_account(filename=str(HERE / CFG["service_account_json"]))
    return gc.open_by_key(CFG["daily_report_id"]), gc.open_by_key(CFG["price_history_id"])

def write_chunks(ws, start_row, rows, ncols):
    for k in range(0, len(rows), 110):
        part = rows[k:k + 110]
        a1 = f"A{start_row + k}"
        ws.update(values=[[("" if v is None else v) for v in r] + [""] * (ncols - len(r)) for r in part], range_name=a1, value_input_option="RAW")

# --------------------------------------------------------------------------------------
# Notification
# --------------------------------------------------------------------------------------
def notify(title, body):
    if sys.platform == "darwin":
        try:
            subprocess.run(["osascript", "-e", f'display notification {json.dumps(body[:240])} with title {json.dumps(title)}'], timeout=10)
        except Exception: pass
    topic = CFG.get("ntfy_topic")
    if topic:
        try:
            import urllib.request
            req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), headers={"Title": title.encode("utf-8").decode("latin-1", "ignore")})
            urllib.request.urlopen(req, timeout=20)
        except Exception as e:
            log("ntfy failed:", e)

# --------------------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pametno", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", action="store_true", help="show the browser window")
    a = ap.parse_args()
    if CFG.get("stop_after") and TODAY > CFG["stop_after"]:
        notify("Store promotions", "Black Friday checker: season is over – you can remove the scheduled job."); return
    from playwright.sync_api import sync_playwright
    fails = []
    with sync_playwright() as pw:
        br = Browser(pw, headless=not a.show)
        try:
            raw = load("raw.json") or {}
            # ---- Gigatron
            if "gigatron" not in raw:
                try:
                    g, f = crawl_gigatron(br); fails += [f"Gigatron {x}" for x in f]
                    watch = search_gigatron(br, WATCH_TERMS + ["G20 Max", "Xiaomi G20"] + G2_TERMS + G3_TERMS)
                    raw["gigatron"] = g; raw["gigatron_search"] = dict(zip(WATCH_TERMS + ["G20 Max", "Xiaomi G20"] + G2_TERMS + G3_TERMS, watch)); save("raw.json", raw)
                    log("Gigatron", len(g))
                except Exception as e:
                    log("Gigatron failed:", str(e).splitlines()[0]); fails.append(f"Gigatron failed: {str(e).splitlines()[0][:100]}"); raw["gigatron"] = []; raw["gigatron_search"] = {}
            # ---- WinWin / Tehnomanija
            for key, home, bases in [("winwin", "https://www.winwin.rs", ["/black-friday?product_list_order=saving"]),
                                     ("tehnomanija", "https://www.tehnomanija.rs", ["/crni-petak", "/crni-petak-vec-sad"])]:
                if key in raw: continue
                if key in [x.lower() for x in CFG.get("skip_stores", [])]:
                    raw[key] = []; raw[key + "_search"] = {}; log(f"{key}: skipped (config skip_stores)"); continue
                log(f"{key}: crawling promo pages…")
                try:
                    r = crawl_magento(br, home, bases)
                    log(f"{key}: {len(r['items'])} promo items, running site searches…")
                    fails += [f"{key} {x}" for x in r["fails"]]
                    s = search_magento(br, (WATCH_TERMS if key == "winwin" else []) + ["G20 Max", "Xiaomi G20", "tablet LTE", "tablet 5G", "RTX 5060", "RTX 5070", "RTX 5080", "32GB", "MacBook Pro"])
                    raw[key] = r["items"]; raw[key + "_search"] = s; save("raw.json", raw); log(key, len(r["items"]), "of", r["total"])
                except Exception as e:
                    log(f"{key} failed:", str(e).splitlines()[0]); fails.append(f"{key} failed: {str(e).splitlines()[0][:100]}"); raw[key] = []; raw[key + "_search"] = {}
            # ---- Big Bang
            if "bigbang" not in raw:
                try:
                    log("Big Bang: crawling…")
                    r = crawl_bigbang(br); fails += [f"Big Bang {x}" for x in r["fails"]]
                    raw["bigbang"] = r["items"]; raw["bigbang_search"] = search_bigbang(br, ["G20 Max", "Xiaomi G20", "tablet 5G", "Galaxy Tab 5G", "RTX 5060", "RTX 5070", "RTX 5080", "MacBook Pro"])
                    save("raw.json", raw); log("Big Bang", len(r["items"]))
                except Exception as e:
                    log("Big Bang failed:", str(e).splitlines()[0]); fails.append(f"Big Bang failed: {str(e).splitlines()[0][:100]}"); raw["bigbang"] = []; raw["bigbang_search"] = {}
            # ---- Ananas
            if "ananas" not in raw:
                try:
                    log("Ananas: crawling…")
                    r = crawl_ananas(br); fails += [f"Ananas {x}" for x in r["fails"]]
                    raw["ananas_all"] = r["all"]; raw["ananas_search"] = search_ananas(br, ["G20 Max", "Xiaomi G20", "tablet LTE", "tablet 5G", "RTX 5070", "RTX 5060", "RTX 5080", "MacBook Pro"])
                    raw["ananas"] = True; save("raw.json", raw); log("Ananas", len(r["all"]))
                except Exception as e:
                    log("Ananas failed:", str(e).splitlines()[0]); fails.append(f"Ananas failed: {str(e).splitlines()[0][:100]}"); raw["ananas_all"] = []; raw["ananas_search"] = {}; raw["ananas"] = True
            if "emmezeta" not in raw:
                try: raw["emmezeta"] = emmezeta_status(br)
                except Exception as e: raw["emmezeta"] = f"Emmezeta check failed: {e}"
                save("raw.json", raw)
            # ---- FULL CATALOGUE (every article in the electronics/appliance categories)
            if CFG.get("mode", "full") == "full":
                import catalog; catalog.FULL_MINUTES = CFG.get("full_store_minutes", 60)
                for key, fn in [("full_gigatron", lambda: catalog.full_gigatron(br, log)),
                                ("full_winwin", lambda: catalog.full_magento(br, "WinWin", "https://www.winwin.rs", log)),
                                ("full_tehnomanija", lambda: catalog.full_magento(br, "Tehnomanija", "https://www.tehnomanija.rs", log)),
                                ("full_bigbang", lambda: catalog.full_bigbang(br, log)),
                                ("full_ananas", lambda: catalog.full_ananas(br, log))]:
                    if key in raw: continue
                    if key.replace("full_", "") in [x.lower().replace(" ", "") for x in CFG.get("skip_stores", [])]:
                        raw[key] = []; log(f"{key}: skipped (config skip_stores)"); continue
                    log(f"{key}: crawling full catalogue…")
                    try:
                        its, f = fn(); fails += f
                    except Exception as e:
                        its = []; fails.append(f"{key} crashed: {e}"); log(key, "crashed:", e)
                    raw[key] = its; save("raw.json", raw)

            # ---- assemble promo items
            items = []
            for x in raw["gigatron"]:
                items.append(dict(store="Gigatron", cat=x.get("cat", ""), name=x["n"], p=x["p"], o=x.get("o"), l=x.get("l"), u=x["u"]))
            for key, st in [("winwin", "WinWin"), ("tehnomanija", "Tehnomanija")]:
                for x in raw[key]: items.append(dict(store=st, cat=x.get("cat", ""), name=x["n"], p=x["p"], o=x.get("o"), l=x.get("l"), u=x["u"]))
            for x in raw["bigbang"]:
                if x["p"] >= 3_000_000: continue   # data glitch guard (e.g. 10,000,000 RSD fridge)
                items.append(dict(store="Big Bang", cat=x.get("c") or "", name=x["n"], p=int(x["p"]), o=int(round(x["p"] + x["d"])), l=None, u=""))
            for x in raw["ananas_all"]:
                if x.get("o") and x.get("p") and x["o"] > x["p"]:
                    items.append(dict(store="Ananas", cat=f"{x['cat']} · seller {x['s']}", name=x["n"], p=x["p"], o=x["o"], l=x.get("l"), u=x["u"]))
            seen, uniq = set(), []
            for it in items:
                if not it["p"] or it["p"] < MIN_PRICE or not it.get("o") or it["o"] <= it["p"]: continue
                k = (it["store"], it["name"], it["p"])
                if k in seen: continue
                seen.add(k); it["term"] = term_for(it["name"]); uniq.append(it)
            # ---- merge full catalogue
            all_items = []
            for key in ["full_gigatron", "full_winwin", "full_tehnomanija", "full_bigbang", "full_ananas"]:
                for x in raw.get(key, []):
                    if not x.get("p") or x["p"] >= 3_000_000: continue
                    all_items.append(dict(store=x["store"], cat=x.get("cat", ""), name=x["n"], p=int(x["p"]), o=x.get("o"), l=x.get("l"), u=x.get("u", "")))
            known = {(i["store"], i["name"]) for i in items}
            for a_ in all_items:
                if (a_["store"], a_["name"]) in known: continue
                if a_["p"] >= MIN_PRICE and a_.get("o") and a_["o"] > a_["p"]:
                    a_ = dict(a_); a_["term"] = term_for(a_["name"]); items.append(a_); known.add((a_["store"], a_["name"]))
            in_all = {(x["store"], x["name"]) for x in all_items}
            all_items += [dict(i) for i in items if (i["store"], i["name"]) not in in_all]
            # ---- own price history (SQLite) + price drops vs last run
            import catalog
            hist_db = catalog.History(HERE / "history.sqlite")
            drops = []
            for a_ in all_items:
                lo, last, n = hist_db.observed(TODAY, a_["store"], a_.get("u", ""), a_["name"])
                a_["l_obs"], a_["obs_days"] = lo, n
                if last and a_["p"] < last * 0.97 and a_["p"] >= CFG.get("drops_min_price", MIN_PRICE):
                    drops.append(dict(a_, last=last))
            obs = {(a_["store"], a_["name"]): (a_["l_obs"], a_["obs_days"]) for a_ in all_items}
            for it in items:
                it["l_obs"], it["obs_days"] = obs.get((it["store"], it["name"]), (None, 0))
            for it in items:
                if not it.get("term"): it["term"] = term_for(it["name"])
            hist_db.save(TODAY, all_items)
            cross_store(all_items, items)
            save("all_items.json", all_items)
            log("all articles:", len(all_items), "| promo items >=15k:", len(items), "| price drops vs last run:", len(drops))

            # ---- watch-group candidates
            watch = build_watch_candidates(raw)
            # ---- pametno
            pm = {}
            if not a.no_pametno and CFG.get("pametno_scope", "promos") != "none":
                def prio(i):
                    rl = (1 - i["p"] / i["l"]) if i.get("l") else None
                    return (0 if (rl is not None and rl >= .05) else 1 if not i.get("l") else 2, -i["p"])
                terms = []
                for it in sorted(items, key=prio):
                    if it["term"] not in terms: terms.append(it["term"])
                wterms = [w["term"] for w in watch if w["term"] not in terms]
                if CFG.get("pametno_scope") == "all":
                    for x in sorted(all_items, key=lambda x: -x["p"]):
                        if x["p"] >= MIN_PRICE:
                            t_ = term_for(x["name"])
                            if t_ not in terms: terms.append(t_)
                terms = terms[: CFG.get("pametno_max_terms", 1500)]
                pm = run_pametno(br, list(dict.fromkeys(wterms + terms)))
        finally:
            br.close()

    analyse(items, pm)
    for w in watch:
        r = pm.get(w["term"]); w["r"] = r if (r and not r.get("e")) else None
    save("items.json", items)
    report = write_outputs(items, watch, raw, pm, fails, dry=a.dry_run, all_items=all_items, drops=drops)
    (OUT / "report.txt").write_text(report, encoding="utf-8")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pw_site", HERE / "pw_site.py"); pw_site = importlib.util.module_from_spec(spec); spec.loader.exec_module(pw_site)
        page = pw_site.build(OUT, TODAY); log("website:", page)
        if CFG.get("open_site"): subprocess.run(["open", str(page)])
    except Exception as e:
        log("website build failed:", e)
    notify(f"Store promotions – {TODAY}", report)
    log("done")

def build_watch_candidates(raw):
    W = []
    def add(group, store, name, p, o=None, l=None, u=""):
        if not p: return
        if group == "G1" and (not re.search(r"G20\s*Max", name, re.I) or re.search(r"Lite|robot", name, re.I)): return
        if group == "G2" and not (re.search(SIM_RE, name, re.I) and re.search(r"tab|pad|tablet", name, re.I)): return
        if group == "G2" and re.search(r"refab|refurb|futrol|maska", name, re.I): return
        if group == "G3":
            ok, _ = laptop_spec(name)
            if not ok: return
        key = (group, store, name)
        if any((x["group"], x["store"], x["name"]) == key for x in W): return
        W.append(dict(group=group, store=store, name=name, p=int(p), o=o, l=l, u=u,
                      term="G20 Max" if group == "G1" else term_for(name)))
    gs = raw.get("gigatron_search", {})
    for q in ["G20 Max", "Xiaomi G20"]:
        for x in gs.get(q) or []: add("G1", "Gigatron", x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
    for q in G2_TERMS:
        for x in gs.get(q) or []: add("G2", "Gigatron", x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
    for x in raw.get("gigatron", []):
        if x.get("cat") == "tablet-racunari": add("G2", "Gigatron", x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
    for q in G3_TERMS:
        for x in gs.get(q) or []: add("G3", "Gigatron", x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
    for key, st in [("winwin_search", "WinWin"), ("tehnomanija_search", "Tehnomanija")]:
        for q, res in (raw.get(key) or {}).items():
            for x in res or []:
                grp = "G1" if "G20" in q else "G2" if "tablet" in q else "G3" if (re.search(r"RTX|32GB|MacBook", q)) else None
                if grp: add(grp, st, x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
    for q, res in (raw.get("bigbang_search") or {}).items():
        for x in res or []:
            grp = "G1" if "G20" in q else "G2" if "Tab" in q or "tablet" in q else "G3"
            add(grp, "Big Bang", x["n"], x["p"], int(x["p"] + x["d"]) if x.get("d") else None, None, "")
    for x in raw.get("ananas_all", []):
        if x["cat"] == "tableti": add("G2", f"Ananas ({x['s']})", x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
        if x["cat"] == "laptop-racunari": add("G3", f"Ananas ({x['s']})", x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
    for q, res in (raw.get("ananas_search") or {}).items():
        for x in res or []:
            grp = "G1" if "G20" in q else "G2" if "tablet" in q else "G3"
            add(grp, f"Ananas ({x['s']})", x["n"], x["p"], x.get("o"), x.get("l"), x["u"])
    return W

def write_outputs(items, watch, raw, pm, fails, dry, all_items=(), drops=()):
    STORES = ["Gigatron", "WinWin", "Tehnomanija", "Big Bang", "Ananas", "Emmezeta"]
    def r12(i):
        r = i.get("r")
        return [i["v"], i["store"], i["cat"], i["name"], i["p"], i["o"], i["claimed"], (i.get("l_used") or "") if i.get("own_src") != "our record" else f'{i["l_used"]} (our record)', "" if i["real"] is None else i["real"],
                i["mkt"] or "", round(i["p"] / i["mkt"] - 1, 4) if i["mkt"] else "", r["t"] if (r and i["mcheck"] == "OK") else (i["mcheck"] if i["mcheck"] not in ("OK", "NOT CHECKED") else "")]
    real = sorted([i for i in items if i["v"].startswith("REAL CUT")], key=lambda i: -i["real"])
    raised = sorted([i for i in items if i["v"].startswith("PRICE RAISED")], key=lambda i: i["real"])
    allp = sorted(items, key=lambda i: (STORES.index(i["store"]), i["v"], -i["p"]))
    summ = []
    for s in STORES:
        it = [i for i in items if i["store"] == s]
        w = [i for i in it if i.get("l")]
        summ.append([s, len(it), round(sum(i["claimed"] for i in it) / len(it), 4) if it else "", len(w),
                     sum(1 for i in w if i["real"] >= .05), sum(1 for i in w if i["real"] < .05 and i["p"] <= i["l"] * 1.02),
                     sum(1 for i in w if i["p"] > i["l"] * 1.02), round(sum(i["real"] for i in w) / len(w), 4) if w else ""])
    ORDER = ["BUY-WORTHY", "BEST IN MARKET", "GOOD", "OK", "SKIP", "SINGLE SELLER", "MODEL VARIANT DIFFERS", "STORAGE DIFFERS",
             "UNCERTAIN MATCH", "LISTED, NO CURRENT OFFERS", "NOT ON PAMETNO", "LOOKUP FAILED", "NOT CHECKED"]
    dd = []
    for i in items:
        r = i.get("r") or {}
        ok = i["mcheck"] == "OK"
        sav = (r.get("md") - i["p"]) if ok and r.get("md") else ""
        dd.append([i["mv"], i["store"], i["name"], i["p"], i["v"], r.get("b") if ok else "", r.get("bs", "") if ok else "", r.get("s2") or "" if ok else "",
                   r.get("n", "") if ok else "", r.get("md") or "" if ok else "", r.get("hi") or "" if ok else "",
                   round(i["p"] / r["b"] - 1, 4) if ok and r.get("b") else "", round(sav) if sav != "" else "",
                   round(sav / r["md"], 4) if sav != "" and r.get("md") else "", r.get("nx", "") if ok else "", r.get("u", ""), TODAY])
    dd.sort(key=lambda x: (ORDER.index(x[0]) if x[0] in ORDER else 99, -(x[13] if isinstance(x[13], float) else -9)))
    mvc = Counter(i["mv"] for i in items)
    # watch rows
    wrows = []
    for g, label in [("G1", "G1 Xiaomi G20 Max"), ("G2", "G2 Tablet with SIM"), ("G3", "G3 Design laptop")]:
        ws = [w for w in watch if w["group"] == g]
        def score(w):
            real = (1 - w["p"] / w["l"]) if w.get("l") else 0
            r = w.get("r"); below = (r and r.get("b") and w["p"] < r["b"] * 0.99)
            return (0 if real >= .05 else 1 if below else 2, w["p"])
        ws.sort(key=score)
        for w in ws[: (50 if g == "G1" else 15)]:
            r = w.get("r") or {}
            spec = "Stick vacuum" if g == "G1" else tablet_spec(w["name"]) if g == "G2" else laptop_spec(w["name"])[1]
            wreal = round(1 - w["p"] / w["l"], 4) if w.get("l") else ""
            mv = market_verdict(w["p"], r) if r.get("n") else "NOT ON PAMETNO / unchecked"
            wrows.append([label, w["store"], w["name"], spec, w["p"], w.get("o") or "", w.get("l") or "", wreal, r.get("b") or "", r.get("bs", ""), r.get("n", ""), mv, w.get("u") or r.get("u", ""), TODAY])
    pm_done = sum(1 for v in pm.values() if v is not None)
    cat_counts = Counter(a["store"] for a in all_items)
    notes_cat = [["Full catalogue crawled (all articles)", "; ".join(f"{k} {v}" for k, v in cat_counts.most_common()) or "promo pages only"],
                 ["Price drops ≥3% vs last run (all articles)", len(drops)]]
    # local CSV of the whole catalogue (opens in Excel)
    import csv
    with open(OUT / "catalogue.csv", "w", newline="", encoding="utf-8-sig") as f:
        wcsv = csv.writer(f); wcsv.writerow(["Store", "Category", "Product", "Price", "Crossed-out", "Store 30-day low", "Our 30-day low", "Days of history", "URL"])
        for a_ in sorted(all_items, key=lambda x: (x["store"], x.get("cat", ""), x["name"])):
            wcsv.writerow([a_["store"], a_.get("cat", ""), a_["name"], a_["p"], a_.get("o") or "", a_.get("l") or "", a_.get("l_obs") or "", a_.get("obs_days", 0), a_.get("u", "")])
    drop_rows = [[d["store"], d.get("cat", ""), d["name"], d["p"], d["last"], round(1 - d["p"] / d["last"], 4), d.get("o") or "", d.get("l") or "",
                  d.get("l_obs") or "", d.get("u", ""), TODAY] for d in sorted(drops, key=lambda d: -(d["last"] - d["p"]))]
    notes = notes_cat + [[]] + [["Notes"], ["Big Bang shows no 30-day low and marks everything −20%; judged only against the market."], [raw.get("emmezeta", "")],
             [f"pametno.rs lookups: {pm_done}/{len(set(i['term'] for i in items))}"], ["Failures: " + ("; ".join(fails) if fails else "none")]]
    # ---- text report
    def fmt(n): return f"{int(n):,}".replace(",", ".")
    prev = set()
    lines = [f"Store promotions – {TODAY}", "", "Biggest real cuts:"]
    gc_hist = None
    if not dry:
        rep, hist = sheets()
        try:
            sp = hist.worksheet("Store promos").get_all_values()[1:]
            dates = sorted({r[0] for r in sp if r and r[0] < TODAY})
            if dates: prev = {(r[1], r[3]) for r in sp if r[0] == dates[-1] and r[10].startswith("REAL CUT")}
        except Exception as e: log("history read failed", e)
    for i in sorted(real, key=lambda i: -(i["l_used"] - i["p"]))[:8]:
        new = "" if (i["store"], i["name"]) in prev else " · NEW"
        lines.append(f"• {i['name'][:60]} · {i['store']} · {fmt(i['p'])} · −{i['real']*100:.0f}% (−{fmt(i['l_used']-i['p'])}) · {i['mv']}{new}")
    lines += ["", "Cheaper than the rest of the market:"]
    for i in sorted([i for i in items if i["mv"] in ("BUY-WORTHY", "BEST IN MARKET")], key=lambda i: i["p"] / i["mkt"])[:8]:
        flag = " (own discount fake)" if i["v"].startswith(("FAKE", "No real")) else ""
        lines.append(f"• {i['name'][:55]} · {i['store']} · {fmt(i['p'])} · {i['mv']}{flag}")
    lines += ["", "Real deals (real cut + cheapest in market):"]
    rd = [i for i in real if i["mv"] in ("BUY-WORTHY", "BEST IN MARKET")]
    lines += [f"• {i['name'][:55]} · {i['store']} · {fmt(i['p'])}" for i in rd[:8]] or ["• none today"]
    lines += ["", "Watch items:"]
    g1 = sorted([w for w in wrows if w[0].startswith("G1")], key=lambda w: w[4])
    if g1: lines.append(f"• G20 Max cheapest: {g1[0][1]} {fmt(g1[0][4])}")
    for g in ("G2", "G3"):
        for w in [w for w in wrows if w[0].startswith(g)][:3]:
            lines.append(f"• {g}: {w[2][:50]} · {w[1]} · {fmt(w[4])} · {w[3]}")
    lines += ["", "Inflated discounts:"]
    for i in raised[:3]: lines.append(f"• {i['name'][:50]} · {i['store']} · claims −{i['claimed']*100:.0f}% but {abs(i['real'])*100:.0f}% ABOVE own 30-day low")
    ov = sorted([i for i in items if i["mkt"]], key=lambda i: -(i["p"] / i["mkt"]))[:3]
    for i in ov: lines.append(f"• {i['name'][:50]} · {i['store']} · +{(i['p']/i['mkt']-1)*100:.0f}% vs market best")
    lines += ["", f"Price drops vs last run (all articles ≥{MIN_PRICE:,}): {len(drops)}"]
    for d in sorted(drops, key=lambda d: -(d["last"] - d["p"]))[:5]:
        lines.append(f"• {d['name'][:50]} · {d['store']} · {fmt(d['last'])} → {fmt(d['p'])}")
    lines += ["", "Per store:"]
    for s in summ: lines.append(f"• {s[0]}: {cat_counts.get(s[0], 0)} articles crawled / {s[1]} promos ≥15k / {s[4]} real cuts / {s[6]} raised")
    lines.append(f"• {raw.get('emmezeta','')}")
    lines += ["", f"Status: pametno {pm_done}/{len(set(i['term'] for i in items))}; failures: {'; '.join(fails) if fails else 'none'}",
              f"https://docs.google.com/spreadsheets/d/{CFG['daily_report_id']}/edit"] + ([f"Website: {CFG['site_url']}"] if CFG.get("site_url") else [])
    report = "\n".join(lines)
    save("site_extra.json", {"summary": summ, "watch": wrows, "drops": drop_rows})
    if dry:
        save("dry_rows.json", {"real": [r12(i) for i in real], "raised": [r12(i) for i in raised], "deep": dd, "watch": wrows}); return report

    # ---- write DAILY REPORT
    title = f"Black Friday store promotions – verified (Belgrade, {TODAY})"
    hdr12 = ["Verdict", "Store", "Category", "Product", "Promo price (RSD)", "Crossed-out price", "Claimed discount", "Store's own 30-day lowest",
             "Real discount vs own 30-day low", "Market low elsewhere (pametno)", "vs market low", "Matched market product"]
    ws = rep.worksheet("Summary"); ws.batch_clear(["A1:Z200"])
    srows = [[title], ["Promo items ≥15,000 RSD; each checked vs the store's own 30-day low and vs all pametno.rs competitors."], [],
             ["Store", "Promoted items checked", "Avg claimed discount", "Items with own 30-day low", "Real cuts (≥5% below own 30-day low)",
              "Price = 30-day low (fake discount)", "Price ABOVE own 30-day low", "Avg real discount"]] + summ + [[], ["Market deep dive verdict", "Items"]] + \
            [[k, v] for k, v in mvc.most_common()] + [[]] + notes
    write_chunks(ws, 1, srows, 8)
    for name, rows in [("Real cuts", [r12(i) for i in real]), ("Price raised", [r12(i) for i in raised]), ("All promos", [r12(i) for i in allp])]:
        w = rep.worksheet(name); w.batch_clear(["A1:N5000"]); write_chunks(w, 1, [hdr12] + rows, 12)
    w = rep.worksheet("Market deep dive"); w.batch_clear(["A1:Q5000"])
    write_chunks(w, 1, [["Verdict", "Store", "Product", "Promo price (RSD)", "Own 30-day check", "Best price (RSD)", "Best store", "2nd cheapest", "Stores",
                         "Market median", "Highest", "Promo vs best", "Saving vs median (RSD)", "Saving vs median %", "Next cheapest stores", "Link", "Date"]] + dd, 17)
    w = rep.worksheet("Watch items"); w.batch_clear(["A1:N500"])
    write_chunks(w, 1, [["Watch group", "Store", "Product", "Key specs (GPU / RAM / storage / SIM)", "Price (RSD)", "Crossed-out price", "Own 30-day lowest",
                         "Real discount vs own 30-day low", "Market best (pametno)", "Best store", "Stores", "Market verdict", "Link", "Date"]] + wrows, 14)
    def tab(book, name, rows, cols):
        try: w_ = book.worksheet(name)
        except Exception: w_ = book.add_worksheet(title=name, rows=max(100, len(rows) + 10), cols=cols)
        if w_.row_count < len(rows) + 5: w_.add_rows(len(rows) + 5 - w_.row_count)
        w_.batch_clear([f"A1:{chr(64 + cols)}{max(len(rows) + 50, 1000)}"]); write_chunks(w_, 1, rows, cols); return w_
    tab(rep, "Price drops", [["Store", "Category", "Product", "Price today (RSD)", "Price last run", "Drop", "Crossed-out", "Store 30-day low",
                              "Our 30-day low", "URL", "Date"]] + drop_rows, 11)
    if CFG.get("write_full_catalogue_sheet"):
        rows_ = [["Store", "Category", "Product", "Price", "Crossed-out", "Store 30-day low", "Our 30-day low", "URL"]] + \
                [[a_["store"], a_.get("cat", ""), a_["name"], a_["p"], a_.get("o") or "", a_.get("l") or "", a_.get("l_obs") or "", a_.get("u", "")]
                 for a_ in sorted(all_items, key=lambda x: (x["store"], x["name"]))]
        tab(rep, "Full catalogue", rows_, 8)
    sid = {s.title: s.id for s in rep.worksheets()}
    rep.batch_update({"requests": [
        {"updateSheetProperties": {"properties": {"sheetId": sid["Summary"], "gridProperties": {"frozenRowCount": 4}}, "fields": "gridProperties.frozenRowCount"}}] +
        [{"updateSheetProperties": {"properties": {"sheetId": sid[n], "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}}
         for n in ["Real cuts", "Price raised", "All promos", "Watch items", "Price drops"] + (["Full catalogue"] if CFG.get("write_full_catalogue_sheet") else [])] +
        [{"updateSheetProperties": {"properties": {"sheetId": sid["Market deep dive"], "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 3}},
          "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
         {"setBasicFilter": {"filter": {"range": {"sheetId": sid["Market deep dive"], "startRowIndex": 0, "endRowIndex": len(dd) + 1, "startColumnIndex": 0, "endColumnIndex": 17}}}}]})
    # verification: read back and compare totals
    back = rep.worksheet("All promos").get(f"E2:E{len(allp)+1}", value_render_option="UNFORMATTED_VALUE")
    s1 = sum(float(r[0]) for r in back if r and r[0] != ""); s0 = sum(i["p"] for i in allp)
    back2 = rep.worksheet("Market deep dive").get(f"D2:D{len(dd)+1}", value_render_option="UNFORMATTED_VALUE")
    s2 = sum(float(r[0]) for r in back2 if r and r[0] != ""); s3 = sum(x[3] for x in dd)
    log(f"verify All promos {s1} vs {s0}; deep dive {s2} vs {s3}")
    if abs(s1 - s0) > 0.5 or abs(s2 - s3) > 0.5: report += "\n⚠ Sheet verification mismatch – check the run log."

    # ---- PRICE HISTORY appends
    sp_ws = hist.worksheet("Store promos")
    existing = {(r[0], r[1], r[3]) for r in sp_ws.get_all_values()[1:] if len(r) > 3}
    fake_big = sorted([i for i in items if i["v"].startswith("FAKE")], key=lambda i: -i["claimed"])[:10]
    pick = real + [i for i in items if i["v"] in ("BELOW MARKET LOW", "At market low")] + raised[:15] + fake_big
    rows, done = [], set()
    for i in pick:
        k = (TODAY, i["store"], i["name"])
        if k in existing or k in done: continue
        done.add(k)
        rows.append([TODAY, i["store"], i["cat"], i["name"], i["p"], i["o"], i["claimed"], i.get("l") or "", "" if i["real"] is None else i["real"], i["mkt"] or "", i["v"]])
    for k in range(0, len(rows), 110): sp_ws.append_rows(rows[k:k + 110], value_input_option="RAW")
    gw = hist.worksheet("Gigatron & WinWin")
    grows = []
    for q, res in (raw.get("gigatron_search") or {}).items():
        if q not in WATCH_TERMS: continue
        hit = pick_watch(q, res)
        if hit: grows.append([TODAY, "Gigatron", q, hit["n"], hit["p"], hit.get("o") or "", hit.get("l") or "",
                              round(1 - hit["p"] / hit["o"], 4) if hit.get("o") else "", round(1 - hit["p"] / hit["l"], 4) if hit.get("l") else "", "", hit["u"]])
    for q, res in (raw.get("winwin_search") or {}).items():
        if q not in WATCH_TERMS: continue
        hit = pick_watch(q, res)
        if hit: grows.append([TODAY, "WinWin", q, hit["n"], hit["p"], hit.get("o") or "", hit.get("l") or "",
                              round(1 - hit["p"] / hit["o"], 4) if hit.get("o") else "", round(1 - hit["p"] / hit["l"], 4) if hit.get("l") else "", "", hit["u"]])
    if grows: gw.append_rows(grows, value_input_option="RAW")
    rt = hist.worksheet("Retailers"); vals = rt.get_all_values()
    rt.update(values=[[f"Finding {TODAY}"]], range_name="F1")
    for idx, row in enumerate(vals[1:], start=2):
        for s in summ:
            if row and row[0].strip().lower().startswith(s[0].lower()):
                txt = raw.get("emmezeta", "") if s[0] == "Emmezeta" else f"{TODAY}: {s[1]} promo items ≥15k; {s[4]} real cuts; {s[6]} above own 30-day low; avg claimed {round((s[2] or 0)*100)}%"
                rt.update(values=[[txt]], range_name=f"F{idx}")
    return report

def pick_watch(q, res):
    if not res: return None
    toks = [nz(t).upper() for t in q.replace("GB", "").split()]
    bad = re.compile(r"futrol|maska|case|cover|torba|outlet|refurb|staklo|zaštit|punjač|kabl|igric|kontroler", re.I)
    for x in res:
        n = nz(x["n"]).upper()
        if bad.search(x["n"]): continue
        if all(t in n for t in toks):
            if "S26" in q and "+" not in q and re.search(r"S26\+|Ultra|Plus", x["n"]): continue
            if "Pro 256" in q and "Max" in x["n"] and "Max" not in q: continue
            return x
    return None

if __name__ == "__main__":
    main()
