"""
WinWin full specifications → Supabase table `winwin_specs` (one row per product page, every spec label: value).
Read together with prices through the view `winwin_db` (articles ⋈ winwin_specs, WinWin only).

Which pages are read: every WinWin article seen in the last 7 days that has no specs yet, or whose specs are older
than --refresh-days (default 30). Never-read pages go first, so the first few runs fill the table and later runs
only top it up. Work is saved every batch, so a time limit never loses what was already read.

    python winwin_specs.py                    # normal run (needs SUPABASE_SERVICE_KEY)
    python winwin_specs.py --probe 5          # read 5 pages and print what was found, write nothing
    python winwin_specs.py --minutes 90 --limit 4000
"""
import argparse, datetime as dt, json, sys, time
from playwright.sync_api import sync_playwright

import db
from bf_watch import Browser, log
from catalog import SPECS_JS

HOME = "https://www.winwin.rs"

JS_PAGE = r"""
window.wwSpecs = html => {
  const d = new DOMParser().parseFromString(html, 'text/html'); const out = {};
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const add = (k, v) => { k = clean(k).replace(/:$/, ''); v = clean(v); if (k && v && k.length < 80 && v.length < 500 && !(k in out)) out[k] = v; };
  // Magento "Specifikacija" table first, then any other 2-column table, then dl lists
  const tables = [...d.querySelectorAll('#product-attribute-specs-table, .additional-attributes, .product-specs table, .data.table')];
  tables.forEach(t => t.querySelectorAll('tr').forEach(tr => { const c = tr.querySelectorAll('th,td'); if (c.length === 2) add(c[0].textContent, c[1].textContent); }));
  if (Object.keys(out).length < 3) d.querySelectorAll('tr').forEach(tr => { const c = tr.querySelectorAll('th,td'); if (c.length === 2) add(c[0].textContent, c[1].textContent); });
  if (Object.keys(out).length < 3) d.querySelectorAll('dt').forEach(dt => { const dd = dt.nextElementSibling; if (dd && dd.tagName === 'DD') add(dt.textContent, dd.textContent); });
  if (Object.keys(out).length < 3 && window.specKV) { const kv = specKV(html); for (const k in kv) add(k, kv[k]); }
  // JSON-LD Product: brand, sku, gtin, availability
  let ld = {};
  d.querySelectorAll('script[type="application/ld+json"]').forEach(s => { try {
    const walk = o => { if (!o || typeof o !== 'object') return; if (Array.isArray(o)) return o.forEach(walk);
      if (o['@type'] === 'Product' || (Array.isArray(o['@type']) && o['@type'].includes('Product'))) ld = o; if (o['@graph']) walk(o['@graph']); };
    walk(JSON.parse(s.textContent)); } catch (e) {} });
  const offer = Array.isArray(ld.offers) ? ld.offers[0] : (ld.offers || {});
  const brand = typeof ld.brand === 'string' ? ld.brand : (ld.brand && ld.brand.name) || out['Brend'] || out['Proizvođač'] || null;
  const name = clean(ld.name || (d.querySelector('h1') || {}).textContent || '');
  return { specs: out, name: name || null, brand: brand ? clean(brand) : null, sku: ld.sku ? String(ld.sku) : null,
           gtin: String(ld.gtin13 || ld.gtin || ld.ean || '') || null,
           availability: offer.availability ? String(offer.availability).split('/').pop() : null };
};
true;
"""

def todo_list(refresh_days, limit):
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    arts = db.select("articles", f"select=url,name&store=eq.WinWin&last_seen=gte.{since}")
    known = {r["url"]: r for r in db.select("winwin_specs", "select=url,fetched_at,n_specs")}
    now = dt.datetime.now(dt.timezone.utc)
    new, stale = [], []
    for a in arts:
        k = known.get(a["url"])
        if not k: new.append(a["url"]); continue
        age = (now - dt.datetime.fromisoformat(k["fetched_at"].replace("Z", "+00:00"))).days
        if age >= refresh_days or (k["n_specs"] == 0 and age >= 7): stale.append((age, a["url"]))
    stale.sort(reverse=True)
    urls = new + [u for _, u in stale]
    log(f"WinWin specs: {len(arts)} live articles, {len(known)} already in the table, {len(new)} never read, {len(stale)} due for refresh")
    return urls[:limit]

def read_batch(br, urls):
    return br.js(r"""async (urls)=>{ const out=[];
      await pool(urls, 4, async u=>{ const t=await ft2(u); const st=window.__st||0;
        if(t==null){ out.push({url:u, http_status:0}); return; }
        let r={specs:{}}; try{ r=wwSpecs(t); }catch(e){}
        out.push({url:u, http_status:st, ...r}); }, 250);
      return out; }""", urls)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=100, help="stop starting new batches after this many minutes")
    ap.add_argument("--limit", type=int, default=20000, help="max product pages this run")
    ap.add_argument("--refresh-days", type=int, default=30)
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--probe", type=int, default=0, help="read N pages, print, write nothing")
    ap.add_argument("--headful", action="store_true")
    a = ap.parse_args()
    if not db.enabled(): sys.exit("SUPABASE_SERVICE_KEY is not set")

    urls = todo_list(a.refresh_days, a.probe or a.limit)
    if not urls: log("WinWin specs: nothing to do"); return
    t0 = time.time(); saved = with_specs = 0
    with sync_playwright() as pw:
        br = Browser(pw, headless=not a.headful)
        br.go(HOME); br.page.evaluate(SPECS_JS); br.page.evaluate(JS_PAGE)
        for i in range(0, len(urls), a.batch):
            if (time.time() - t0) / 60 > a.minutes: log("WinWin specs: time limit reached, the rest goes next run"); break
            part = urls[i:i + a.batch]
            try:
                res = read_batch(br, part)
            except Exception as e:   # page crashed / navigated: reopen and carry on
                log("batch failed, reopening:", str(e).splitlines()[0]); br.go(HOME); br.page.evaluate(SPECS_JS); br.page.evaluate(JS_PAGE); continue
            if a.probe:
                for r in res: print(json.dumps(r, ensure_ascii=False, indent=1)[:3000])
                return
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            rows = [dict(url=r["url"], name=r.get("name"), brand=r.get("brand"), sku=r.get("sku"), gtin=r.get("gtin"),
                         availability=r.get("availability"), specs=r.get("specs") or {}, n_specs=len(r.get("specs") or {}),
                         http_status=r.get("http_status"), fetched_at=now)
                    for r in res if r.get("http_status") and r["http_status"] < 500 and r["http_status"] not in (403, 429)]   # errors / refusals are retried next run
            if rows: db.upsert("winwin_specs", rows, ["url"], chunk=200)
            saved += len(rows); with_specs += sum(1 for r in rows if r["n_specs"])
            blocked = sum(1 for r in res if r.get("http_status") in (403, 429))
            log(f"WinWin specs: {min(i + a.batch, len(urls))}/{len(urls)} pages, saved {saved} ({with_specs} with specs)")
            if blocked > len(res) // 2: log(f"WinWin specs: {blocked} pages refused (403/429) – stopping to stay polite"); break
        br.close()
    log(f"WinWin specs done: {saved} pages saved, {with_specs} with specifications, {round((time.time() - t0) / 60)} min")

if __name__ == "__main__":
    main()
