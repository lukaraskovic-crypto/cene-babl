#!/usr/bin/env python3
"""Saves small samples of what each store returns, so the full-catalogue parsers can be fixed.
Run:  ./.venv/bin/python probe.py      (about 1 minute; writes probe/*.txt)"""
import json, re
from pathlib import Path
import bf_watch as b

OUT = b.HERE / "probe"; OUT.mkdir(exist_ok=True)

def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = b.Browser(pw, headless=True)
        try:
            br.go("https://gigatron.rs")
            t = br.js("""async()=>{ const r=await fetch('/api/vtex/plp-search?facetsPath='+encodeURIComponent('category-1/mobilni-telefoni-tableti-i-oprema/category-2/tablet-racunari')+'&page=2');
                         return r.status+'\\n'+(await r.text()); }""")
            (OUT / "gigatron_api.txt").write_text(t[:200000], encoding="utf-8")
            t = br.js("""async()=>{ const x=await (await fetch('/sitemap/kategorije.xml')).text(); return x.slice(0,5000); }""")
            (OUT / "gigatron_categories.txt").write_text(t, encoding="utf-8")
            for name, home in [("winwin", "https://www.winwin.rs"), ("tehnomanija", "https://www.tehnomanija.rs")]:
                br.go(home)
                t = br.js("""async()=>{ const r=await fetch('/'); const h=await r.text(); const links=[...new Set([...new DOMParser().parseFromString(h,'text/html').querySelectorAll('a[href]')].map(a=>a.getAttribute('href')))];
                           return 'status '+r.status+' url '+r.url+' len '+h.length+'\\nTITLE '+((h.match(/<title>([^<]*)/i)||[])[1]||'')+'\\n'+links.slice(0,400).join('\\n'); }""")
                (OUT / f"{name}_home_links.txt").write_text(t, encoding="utf-8")
            br.go("https://www.bigbang.rs")
            t = br.js("""async()=>{ let s=await (await fetch('/sitemap.xml')).text(); const h=await (await fetch('/')).text();
                       const links=[...new Set([...new DOMParser().parseFromString(h,'text/html').querySelectorAll('a[href]')].map(a=>a.getAttribute('href')))];
                       return 'SITEMAP\\n'+s.slice(0,4000)+'\\nHOME LINKS\\n'+links.slice(0,400).join('\\n'); }""")
            (OUT / "bigbang.txt").write_text(t, encoding="utf-8")
            br.go("https://ananas.rs")
            t = br.js("""async()=>{ const h=await (await fetch('/kategorije/bela-tehnika')).text();
                       const links=[...new Set([...new DOMParser().parseFromString(h,'text/html').querySelectorAll('a[href]')].map(a=>a.getAttribute('href')))].filter(l=>/kategorije/.test(l));
                       return links.slice(0,300).join('\\n'); }""")
            (OUT / "ananas_links.txt").write_text(t, encoding="utf-8")
        finally:
            br.close()
    print("saved to", OUT)

if __name__ == "__main__":
    main()
