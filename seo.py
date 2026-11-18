"""
Search-engine pages for cene.babl.cc, written next to the website after every build (also in "site" mode):

    p/<name>-<id>.html     one page per article worth finding (confirmed reductions, other advertised discounts, price drops)
    k/<category>.html      category pages (confirmed reductions first, then the cheapest)
    prodavnica/<store>.html, popusti.html, crni-petak.html
    sitemap.xml, robots.txt, seo.css

Every page is plain HTML (readable without JavaScript) and links to the live site (/#a=<id>) for the full tool.
    python seo.py site        # rebuild the pages from site/data*.js
"""
import json, re, os, sys, html, unicodedata, datetime as dt
from pathlib import Path

BASE = (os.environ.get("SITE_URL") or "https://cene.babl.cc").rstrip("/")
MAX_PAGES = 5000
MON = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "avg", "sep", "okt", "nov", "dec"]
e = lambda s: html.escape(str(s if s is not None else ""), quote=True)

def nf(n): return f"{int(round(n)):,}".replace(",", ".")
def fold(s): return unicodedata.normalize("NFD", str(s or "").lower().replace("đ", "d")).encode("ascii", "ignore").decode()
def slug(s, n=70): return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", fold(s))).strip("-")[:n].strip("-") or "x"

def hid(store, url, name):
    """Same id as the website's hid() (djb2 over UTF-16 code units, base 36)."""
    s = f"{store}|{'' if store == 'Big Bang' else (url or '')}|{name}"
    b = s.encode("utf-16-le"); h = 5381
    for i in range(0, len(b), 2): h = (h * 33 + (b[i] | b[i + 1] << 8)) & 0xFFFFFFFF
    d = "0123456789abcdefghijklmnopqrstuvwxyz"; o = ""
    while True:
        h, r = divmod(h, 36); o = d[r] + o
        if not h: return o

def VG(v):
    v = v or ""
    if not v: return "none"
    for pre, g in (("REAL CUT", "real"), ("PRICE RAISED", "raised"), ("FAKE", "fake"), ("No real", "nochange")):
        if v.startswith(pre): return g
    return "other"

VNAME = {"real": "Potvrđeno sniženje", "raised": "Iznad 30-dnevnog minimuma", "fake": "Nije niže od 30 dana", "nochange": "Blizu 30-dnevnog minimuma"}
VCLS = {"real": "good", "raised": "bad", "fake": "bad", "nochange": "warn"}
NOTE = ("Ocene su samo poređenje javno objavljenih cena (današnja cena i najniža cena koju prodavnica navodi za prethodnih 30 dana), "
        "ne tvrdnja o namerama prodavca niti pravna ocena. Podaci mogu kasniti ili sadržati greške – pre kupovine proverite cenu kod prodavca. "
        "Sajt nije povezan ni sa jednom prodavnicom.")

def why(a):
    g, l = a["g"], (nf(a["low30"]) + " din" if a["low30"] else "")
    pc = lambda x: f"{round(x * 100)}%"
    if g == "real" and a["low30"]: return f"Cena je {pc(1 - a['price'] / a['low30'])} niža od najniže cene ove prodavnice u 30 dana pre sniženja ({l})."
    if g == "raised" and a["low30"]: return f"Uz artikal je istaknut popust od {pc(a['claimed'])}, a cena je {pc(a['price'] / a['low30'] - 1)} viša od najniže cene koju prodavnica navodi za poslednjih 30 dana ({l})."
    if g == "fake" and a["low30"]: return f"Uz artikal je istaknut popust od {pc(a['claimed'])}, a ista cena ({l}) je prema podacima prodavnice bila najniža i u poslednjih 30 dana."
    if g == "nochange" and a["low30"]: return f"Cena je praktično ista kao najniža u poslednjih 30 dana ({l})."
    return ""

def load(site):
    t = (site / "data.js").read_text(encoding="utf-8")
    data = json.loads(re.match(r"window\.DATA=(\{.*\});window\.DATA\.rows=\[\];$", t.strip(), re.S).group(1))
    rows = []
    for f in sorted(site.glob("data-*.js"), key=lambda p: int(re.findall(r"\d+", p.name)[0])):
        s = f.read_text(encoding="utf-8").strip()
        rows += json.loads(re.match(r"window\.DATA\.rows\.push\(\.\.\.(\[.*\])\);$", s, re.S).group(1))
    return data, rows

def cat_name(c):
    c = re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", re.sub(r"\.html$", "", str(c or "").split(" · seller")[0]))).strip().lower()
    return c[:1].upper() + c[1:] if c else ""

def year_dates(hist, today):
    """History points carry MM-DD; give them a year (a month after today's month belongs to last year)."""
    out = []
    for d, p in hist:
        try: m, dd = int(d[:2]), int(d[3:5])
        except Exception: continue
        y = today.year - (1 if m > today.month else 0)
        out.append((dt.date(y, m, dd), p))
    return out

def svg(hist):
    if len(hist) < 2: return ""
    ps = [p for _, p in hist]; mn, mx = min(ps) * 0.97, max(ps) * 1.03; W, H, L, B = 640, 180, 64, 22
    x = lambda i: L + i / (len(hist) - 1) * (W - L - 8); y = lambda p: H - B - (p - mn) / ((mx - mn) or 1) * (H - B - 8)
    d = f"M{x(0):.1f},{y(hist[0][1]):.1f}" + "".join(f" H{x(i):.1f} V{y(hist[i][1]):.1f}" for i in range(1, len(hist)))
    grid = "".join(f'<text x="0" y="{y(v) + 4:.1f}">{nf(v)}</text><line x1="{L}" x2="{W}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>' for v in (mn, (mn + mx) / 2, mx))
    f0, f1 = hist[0][0], hist[-1][0]
    return (f'<svg class="ch" viewBox="0 0 {W} {H}" role="img" aria-label="Kretanje cene od {f0.day}. {MON[f0.month - 1]} do {f1.day}. {MON[f1.month - 1]}">{grid}'
            f'<path d="{d}"/><text x="{L}" y="{H - 4}">{f0.day}. {MON[f0.month - 1]}</text><text x="{W - 8}" y="{H - 4}" text-anchor="end">{f1.day}. {MON[f1.month - 1]}</text></svg>')

CSS = """:root{--bg:#F6F7F3;--s:#fff;--t:#13201A;--m:#5B6B62;--p:#1F6B45;--b:#DCE3DD;--good:#1F6B45;--goodbg:#E3F3EA;--bad:#B3261E;--badbg:#FBEAE8;--warn:#8A5A00;--warnbg:#FBF1DC}
@media (prefers-color-scheme:dark){:root{--bg:#0E1512;--s:#17211C;--t:#E8F0EA;--m:#9AACA1;--p:#5CC48A;--b:#28362E;--good:#5CC48A;--goodbg:#173326;--bad:#F2B8B5;--badbg:#3A1D1B;--warn:#E8C27A;--warnbg:#33290F}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--p)}.w{max-width:880px;margin:0 auto;padding:0 16px}header{background:var(--s);border-bottom:1px solid var(--b)}
header .w{display:flex;align-items:center;gap:14px;height:56px}.wm{font-weight:800;font-size:20px;color:var(--t);text-decoration:none}.wm b{color:var(--p)}
header nav{margin-left:auto;display:flex;gap:14px;font-size:14px}main{padding:22px 0 40px}.bc{font-size:13px;color:var(--m)}.bc a{color:var(--m)}
h1{font-size:26px;line-height:1.25;margin:8px 0 12px}h2{font-size:18px;margin:28px 0 10px}.pr{font-size:34px;font-weight:800;color:var(--p)}.was{color:var(--m);text-decoration:line-through;margin-left:10px}
.tag{display:inline-block;font-size:13px;font-weight:700;border-radius:99px;padding:3px 10px;margin:6px 6px 0 0}.good{color:var(--good);background:var(--goodbg)}.bad{color:var(--bad);background:var(--badbg)}.warn{color:var(--warn);background:var(--warnbg)}
.box{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:14px 16px;margin:14px 0}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0}dt{font-size:13px;color:var(--m)}dd{margin:0;font-weight:700}
.btn{display:inline-block;padding:9px 16px;border-radius:99px;border:1px solid var(--b);background:var(--s);text-decoration:none;font-weight:700;margin:6px 8px 0 0}.btn.pri{background:var(--p);color:var(--s);border-color:var(--p)}
.ch{width:100%;height:auto}.ch path{fill:none;stroke:var(--p);stroke-width:2.4}.ch line{stroke:var(--b)}.ch text{font-size:11px;fill:var(--m)}
ul.l{list-style:none;padding:0;margin:0}ul.l li{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:10px 14px;margin:8px 0;display:flex;gap:12px;justify-content:space-between;align-items:baseline}
ul.l .n{font-weight:600}ul.l .m{font-size:13px;color:var(--m)}ul.l .p{font-weight:800;white-space:nowrap}.cl{columns:2 220px;font-size:15px}.cl a{display:block;padding:2px 0}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--b);padding:6px 4px;text-align:left}footer{border-top:1px solid var(--b);color:var(--m);font-size:13px;padding:18px 0 40px}"""

# anonymous page-view log for these static pages (same rules as the main site: no cookies, no IPs, no persistent id; DNT/GPC respected)
TJS = r"""(()=>{ try{ if(!/babl\.cc$/.test(location.hostname)||localStorage.getItem('notrack')==='1'||navigator.doNotTrack==='1'||navigator.globalPrivacyControl) return; }catch(e){ return; }
let sid=''; try{ sid=sessionStorage.getItem('sid')||''; }catch(e){}
if(!sid){ sid=(Math.random().toString(36).slice(2)+Date.now().toString(36)).replace(/[^a-z0-9]/g,'').slice(0,24); try{ sessionStorage.setItem('sid',sid); }catch(e){} }
let ref=''; try{ ref=document.referrer?new URL(document.referrer).hostname:''; }catch(e){}
const pth=location.pathname, kind=pth.startsWith('/p/')?'p':pth.startsWith('/k/')?'k':pth.startsWith('/prodavnica/')?'store':pth.replace(/^\/|\.html$/g,'')||'home';
let fs=null; try{ fs=localStorage.getItem('fs'); if(!fs) localStorage.setItem('fs',new Date().toISOString().slice(0,10)); }catch(e){}
const send=rows=>{ try{ fetch('https://hxtdrtsqigvuvhaszxna.supabase.co/rest/v1/rpc/log_events',{method:'POST',keepalive:true,headers:{apikey:'sb_publishable_DPAXHrrEuhxB1ABfXQ7UrQ_azF6yuZ5','Content-Type':'application/json'},body:JSON.stringify({rows})}).catch(()=>{}); }catch(e){} };
const m=matchMedia('(max-width:760px)').matches, t0=Date.now();
send([{sid,ev:'page',q:pth.slice(0,120),ref:ref||'direct',lang:'sr',mobile:m,item:(document.querySelector('h1')||{}).textContent?.slice(0,150),data:{kind,new:!fs}}]);
let done=false; const leave=()=>{ if(done) return; done=true; send([{sid,ev:'leave',q:pth.slice(0,120),lang:'sr',mobile:m,data:{sec:Math.min(3600,Math.round((Date.now()-t0)/1000)),kind}}]); };
addEventListener('pagehide',leave); addEventListener('visibilitychange',()=>{ if(document.visibilityState==='hidden') leave(); });
document.addEventListener('click',e=>{ const a=e.target.closest('a[href^="http"]'); if(!a) return; let h=''; try{ h=new URL(a.href).hostname; }catch(_){}
  if(h&&!/babl\.cc$/.test(h)) send([{sid,ev:'out',store:h.replace(/^www\./,''),item:(document.querySelector('h1')||{}).textContent?.slice(0,150),lang:'sr',mobile:m,data:{from:kind}}]); },true); })();"""

def page(title, desc, path, body, crumbs=(), ld=None, og_type="website"):
    url = BASE + "/" + path
    bc = ('<div class="bc"><a href="/">babl cene</a>' + "".join(f' › <a href="{e(h)}">{e(t)}</a>' if h else f" › {e(t)}" for t, h in crumbs) + "</div>") if crumbs else ""
    lds = [ld] if ld else []
    if crumbs:
        items = [{"@type": "ListItem", "position": 1, "name": "babl cene", "item": BASE + "/"}]
        for k, (t, h) in enumerate(crumbs, 2): items.append({"@type": "ListItem", "position": k, "name": t, **({"item": BASE + h} if h else {})})
        lds.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items})
    ldh = "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False).replace("</", "<\\/") + "</script>" for x in lds)
    return f"""<!doctype html><html lang="sr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{e(url)}">
<meta property="og:type" content="{og_type}"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(url)}"><meta property="og:site_name" content="babl cene"><meta property="og:locale" content="sr_RS">
<meta name="theme-color" content="#1F6B45"><link rel="alternate" type="application/rss+xml" title="babl cene – stvarna sniženja" href="/rss.xml"><link rel="stylesheet" href="/seo.css">{ldh}<script defer src="/t.js"></script></head><body>
<header><div class="w"><a class="wm" href="/">babl <b>cene</b></a><nav><a href="/top10.html">Top 10</a><a href="/popusti.html">Potvrđena sniženja</a><a href="/crni-petak.html">Crni petak</a></nav></div></header>
<main class="w">{bc}{body}</main><footer class="w">{e(NOTE)} <a href="/">Pretraga svih artikala</a> · <a href="/sitemap.xml">Mapa sajta</a></footer></body></html>"""

def li(a, link=True):
    tag = f' <span class="tag {VCLS[a["g"]]}">{VNAME[a["g"]]}</span>' if a["g"] in VNAME else ""
    nm = f'<a href="/{a["path"]}">{e(a["name"])}</a>' if link and a.get("path") else f'<a href="/#a={a["id"]}">{e(a["name"])}</a>'
    old = f' <s>{nf(a["old"])}</s>' if a["old"] > a["price"] else ""
    return f'<li><div><div class="n">{nm}</div><div class="m">{e(a["store"])}{(" · " + e(a["cat"])) if a["cat"] else ""}{tag}</div></div><div class="p">{nf(a["price"])} din<span class="m">{old}</span></div></li>'

def raised_before(a, today):
    """The price went up >= 8% in the last 30 days and the "sale" price is not really below the earlier low."""
    if not a["old"] > a["price"]: return False
    pts = [(today - d).days for d, _ in year_dates(a["hist"], today)]
    lo, peak = None, 0
    for (d, p), ago in zip(year_dates(a["hist"], today), pts):
        if ago > 30: continue
        if lo is None or p < lo: lo, peak = p, 0
        elif p > peak: peak = p
    return bool(lo and peak >= lo * 1.08 and a["price"] >= lo * 0.97)

def top_deals(arts, today, n):
    seen, out = set(), []
    for a in sorted([a for a in arts if a["g"] == "real" and a["low30"] and a["price"] >= 5000 and not (a["xs"] and a["xs"] < a["price"] * 0.98)
                     and not raised_before(a, today)], key=lambda a: -(a["low30"] - a["price"])):
        k = re.sub(r"[^a-z0-9]", "", fold(a["name"]))[:40]
        if k in seen: continue
        seen.add(k); out.append(a)
        if len(out) >= n: break
    return out

def build(site, log=print):
    site = Path(site)
    data, rows = load(site)
    C = {c: i for i, c in enumerate(data["cols"])}
    today = dt.date.fromisoformat(data["date"]); upd = data.get("updated", data["date"])
    arts = []
    for r in rows:
        if not r[C["price"]]: continue
        a = dict(store=r[C["store"]], name=r[C["name"]], price=r[C["price"]], old=r[C["old"]] or 0, low30=r[C["low30"]] or 0, url=r[C["url"]] or "",
                 g=VG(r[C["verdict"]]), cat=cat_name(r[C["cat"]]), xs=r[C["xs_price"]] or 0, xss=r[C["xs_store"]] or "", hist=r[C["hist"]] or [],
                 specs=r[C["specs"]] if isinstance(r[C["specs"]], dict) else {})
        a["id"] = hid(a["store"], a["url"], a["name"])
        a["claimed"] = 1 - a["price"] / a["old"] if a["old"] > a["price"] else 0
        hp = [p for _, p in a["hist"]]
        a["drop"] = (hp[0] - a["price"]) / hp[0] if len(hp) > 1 and hp[0] else 0
        arts.append(a)
    # which articles get their own page: confirmed reductions, other advertised discounts, then the biggest price drops
    pri = lambda a: (0 if a["g"] == "real" else 1 if a["g"] in VNAME else 2, -a["drop"], -a["price"])
    pick = sorted([a for a in arts if a["price"] >= 3000 and (a["g"] in VNAME or a["drop"] >= 0.05)], key=pri)[:MAX_PAGES]
    for a in pick: a["path"] = f"p/{slug(a['name'])}-{a['id']}.html"
    bycat = {}
    for a in arts:
        if a["cat"]: bycat.setdefault(slug(a["cat"], 60), []).append(a)
    cats = {k: v for k, v in bycat.items() if len(v) >= 15}
    catname = {k: max({a["cat"] for a in v}, key=lambda c: (sum(1 for a in v if a["cat"] == c), c != fold(c))) for k, v in cats.items()}

    # clean old pages, write new ones
    for d in ("p", "k", "prodavnica"):
        (site / d).mkdir(parents=True, exist_ok=True)
        for f in (site / d).glob("*.html"): f.unlink()
    (site / "seo.css").write_text(CSS, encoding="utf-8")
    (site / "t.js").write_text(TJS, encoding="utf-8")
    # install on the phone's home screen (icons are committed in static/)
    import shutil
    for f in (Path(__file__).resolve().parent / "static").glob("*"): shutil.copy(f, site / f.name)
    (site / "manifest.webmanifest").write_text(json.dumps({"name": "babl cene – provera popusta", "short_name": "babl cene", "start_url": "/?utm_source=pwa",
        "display": "standalone", "background_color": "#F6F7F3", "theme_color": "#1F6B45", "lang": "sr",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}, {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}, ensure_ascii=False), encoding="utf-8")
    urls = [(BASE + "/", data["date"])]
    W = lambda path, s: ((site / path).write_text(s, encoding="utf-8"), urls.append((BASE + "/" + path, data["date"])))

    for a in pick:
        ck = slug(a["cat"], 60) if a["cat"] else ""
        hist = year_dates(a["hist"], today); hp = [p for _, p in hist] + [a["price"]]
        same = [b for b in cats.get(ck, []) if b is not a and b.get("path")][:8] if ck in cats else []
        w = why(a)
        tag = f'<span class="tag {VCLS[a["g"]]}">{VNAME[a["g"]]}</span>' if a["g"] in VNAME else ""
        fig = [("Precrtana cena", nf(a["old"]) + " din" if a["old"] > a["price"] else "–"), ("Najniža cena pre sniženja", nf(a["low30"]) + " din" if a["low30"] else "–"),
               ("Najniža zabeležena", nf(min(hp)) + " din" if len(hp) > 1 else "–"), ("Najjeftinije drugde", f"{nf(a['xs'])} din ({e(a['xss'])})" if a["xs"] else "–")]
        spec = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in list(a["specs"].items())[:12])
        tbl = "".join(f"<tr><td>{d.day}. {MON[d.month - 1]} {d.year}.</td><td>{nf(p)} din</td></tr>" for d, p in reversed(hist[-12:]))
        body = (f"<h1>{e(a['name'])}</h1><div>{e(a['store'])}{(' · ' + e(a['cat'])) if a['cat'] else ''}</div>"
                f'<div style="margin:12px 0"><span class="pr">{nf(a["price"])} din</span>'
                + (f'<span class="was">{nf(a["old"])} din</span> <b style="color:var(--bad)">−{round(a["claimed"] * 100)}%</b>' if a["claimed"] else "") + f"<br>{tag}</div>"
                + (f'<div class="box"><b>Zašto ova ocena</b><br>{e(w)}</div>' if w else "")
                + '<div class="box"><dl>' + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in fig) + "</dl></div>"
                + f'<p><a class="btn pri" href="/#a={a["id"]}">Prati cenu na babl cene</a>' + (f'<a class="btn" href="{e(a["url"])}" rel="nofollow noopener" target="_blank">Otvori u prodavnici</a>' if a["url"] else "") + "</p>"
                + (f"<h2>Kretanje cene</h2>{svg(hist)}<table>{tbl}</table>" if len(hist) > 1 else "")
                + (f"<h2>Specifikacija</h2><table>{spec}</table>" if spec else "")
                + (f'<h2>Slični artikli – {e(a["cat"])}</h2><ul class="l">' + "".join(li(b) for b in same) + f'</ul><p><a href="/k/{ck}.html">Svi artikli: {e(a["cat"])}</a></p>' if same else "")
                + f'<p class="bc">Cena preuzeta sa sajta prodavnice, ažurirano {e(upd)}.</p>')
        title = f"{a['name'][:70]} – cena {nf(a['price'])} din ({a['store']}) | babl cene"
        desc = (f"{a['name'][:90]}: {nf(a['price'])} din u prodavnici {a['store']}. "
                + (f"{VNAME[a['g']]}. " if a["g"] in VNAME else "") + (f"Najniža cena u 30 dana: {nf(a['low30'])} din. " if a["low30"] else "") + "Istorija cene i poređenje.")[:300]
        ld = {"@context": "https://schema.org", "@type": "Product", "name": a["name"], "category": a["cat"] or None, "url": BASE + "/" + a["path"],
              "offers": {"@type": "Offer", "price": a["price"], "priceCurrency": "RSD", "availability": "https://schema.org/InStock",
                         "url": a["url"] or BASE + "/" + a["path"], "seller": {"@type": "Organization", "name": a["store"]}}}
        ld = {k: v for k, v in ld.items() if v is not None}
        crumbs = ([(a["cat"], f"/k/{ck}.html")] if ck in cats else []) + [(a["name"][:60], "")]
        W(a["path"], page(title, desc, a["path"], body, crumbs, ld, "product"))

    for k, v in cats.items():
        nm = catname[k]
        real = sorted([a for a in v if a["g"] == "real"], key=lambda a: a["price"] / (a["low30"] or a["price"]))[:30]
        cheap = sorted([a for a in v if a["g"] != "real"], key=lambda a: a["price"])[:40]
        stores = sorted({a["store"] for a in v})
        body = (f"<h1>{e(nm)} – cene i provera popusta</h1><p>{nf(len(v))} artikala u prodavnicama {e(', '.join(stores))}. "
                f"Za svaki artikal pratimo cenu svakog dana i poredimo istaknuti popust sa najnižom cenom iz prethodnih 30 dana.</p>"
                + (f'<h2>Potvrđena sniženja ({len(real)})</h2><ul class="l">' + "".join(li(a) for a in real) + "</ul>" if real else "")
                + f'<h2>Najniže cene</h2><ul class="l">' + "".join(li(a) for a in cheap) + "</ul>"
                + f'<p><a class="btn pri" href="/#q={e(nm)}">Pretraži sve: {e(nm)}</a></p>')
        title = f"{nm} – cene, popusti i istorija cena | babl cene"
        desc = f"{nm}: {nf(len(v))} artikala, " + (f"{len(real)} potvrđenih sniženja danas. " if real else "") + "Poređenje cena u Gigatronu, WinWinu, Big Bangu i drugim prodavnicama, sa istorijom cena."
        W(f"k/{k}.html", page(title, desc[:300], f"k/{k}.html", body, [(nm, "")]))

    bystore = {}
    for a in arts: bystore.setdefault(a["store"], []).append(a)
    for s_, v in bystore.items():
        real = sorted([a for a in v if a["g"] == "real"], key=lambda a: a["price"] / (a["low30"] or a["price"]))[:40]
        flag = [a for a in v if a["g"] in ("fake", "raised")]
        sc = sorted({slug(a["cat"], 60) for a in v if a["cat"] and slug(a["cat"], 60) in cats})
        body = (f"<h1>{e(s_)} – popusti i istorija cena</h1><p>Pratimo {nf(len(v))} artikala prodavnice {e(s_)}. Danas: {len(real)} potvrđenih sniženja, "
                f"{len(flag)} istaknutih popusta koji nisu niži od 30-dnevnog minimuma ove prodavnice.</p>"
                + (f'<h2>Potvrđena sniženja</h2><ul class="l">' + "".join(li(a) for a in real) + "</ul>" if real else "")
                + (f'<h2>Kategorije</h2><div class="cl">' + "".join(f'<a href="/k/{c}.html">{e(catname[c])}</a>' for c in sc) + "</div>" if sc else ""))
        p_ = f"prodavnica/{slug(s_)}.html"
        W(p_, page(f"{s_} popusti danas – provera sniženja | babl cene", f"{s_}: {len(real)} potvrđenih sniženja danas, istorija cena za {nf(len(v))} artikala.", p_, body, [(s_, "")]))

    real = sorted([a for a in arts if a["g"] == "real" and a["low30"]], key=lambda a: a["price"] / a["low30"])
    top = real[:120]
    body = (f"<h1>Potvrđena sniženja danas</h1><p>Artikli čija je današnja cena bar 5% niža od najniže cene koju prodavnica navodi za prethodnih 30 dana. "
            f"Ukupno danas: {nf(len(real))}. Ažurirano {e(upd)}.</p><ul class='l'>" + "".join(li(a) for a in top) + "</ul>"
            + '<h2>Po kategorijama</h2><div class="cl">' + "".join(f'<a href="/k/{k}.html">{e(catname[k])}</a>' for k in sorted(cats, key=lambda k: -len(cats[k]))[:80]) + "</div>"
            + '<h2>Po prodavnicama</h2><div class="cl">' + "".join(f'<a href="/prodavnica/{slug(s_)}.html">{e(s_)}</a>' for s_ in sorted(bystore)) + "</div>")
    W("popusti.html", page(f"Potvrđena sniženja danas ({nf(len(real))}) – Gigatron, WinWin, Big Bang… | babl cene",
                           f"{nf(len(real))} artikala je danas zaista jeftinije od najniže cene iz prethodnih 30 dana. Spisak se osvežava više puta dnevno.", "popusti.html", body, [("Potvrđena sniženja", "")]))

    bf = dt.date(today.year, 11, 1); bf += dt.timedelta(days=(4 - bf.weekday()) % 7 + 21)       # 4th Friday of November
    body = (f"<h1>Crni petak {today.year} – koji su popusti stvarni?</h1>"
            f"<p>Crni petak je {bf.day}. novembra {bf.year}. Od 1. maja 2026. prodavnice uz sniženje moraju da navedu i <b>prethodnu cenu</b> – najnižu cenu iz perioda pre sniženja. "
            "babl cene svakog dana poredi tu objavljenu cenu sa današnjom, za oko 100.000 artikala iz Gigatrona, WinWina, Big Banga, Ananasa, Tehnomedie, PC Practica i Eurotehne.</p>"
            '<div class="box"><b>Kako da proverite popust za 30 sekundi</b><ol><li>Pronađite artikal na <a href="/">cene.babl.cc</a> (pretraga radi i bez kvačica).</li>'
            "<li>Pogledajte ocenu: <i>Potvrđeno sniženje</i> znači da je cena bar 5% niža od najniže u prethodnih 30 dana.</li>"
            "<li>Pogledajte grafikon – da li je cena podignuta pre akcije?</li><li>Sačuvajte artikal i uključite e-mail obaveštenje kad cena padne.</li></ol></div>"
            f"<h2>Najveća potvrđena sniženja danas</h2><ul class='l'>" + "".join(li(a) for a in real[:60]) + "</ul>"
            '<p><a class="btn pri" href="/popusti.html">Sva potvrđena sniženja</a><a class="btn" href="/">Pretraga</a></p>')
    W("crni-petak.html", page(f"Crni petak {today.year} – provera popusta (Gigatron, WinWin, Big Bang…) | babl cene",
                              f"Da li je popust za Crni petak {today.year} stvaran? Poredimo cene sa najnižom cenom iz prethodnih 30 dana za 100.000 artikala.", "crni-petak.html", body, [(f"Crni petak {today.year}", "")]))

    # ---- weekly Top 10 (also the RSS feed for Telegram/Viber channels and the text for the owner's morning e-mail)
    top = top_deals(arts, today, 10)
    body = (f"<h1>Top 10 stvarnih sniženja</h1><p>Deset najvećih popusta koji su zaista ispod najniže cene iz 30 dana pre sniženja – bez artikala "
            f"kojima je cena prvo podignuta i bez onih koji su jeftiniji u drugoj prodavnici. Ažurirano {e(upd)}.</p><ol class='l' style='padding:0'>"
            + "".join(li(a).replace("<li>", "<li>", 1) for a in top) + "</ol><p><a class='btn pri' href='/popusti.html'>Sva potvrđena sniženja</a></p>")
    W("top10.html", page(f"Top 10 stvarnih sniženja danas | babl cene", "Deset najvećih stvarnih popusta danas u Gigatronu, WinWinu, Big Bangu, Ananasu i drugim prodavnicama.",
                         "top10.html", body, [("Top 10", "")]))
    items_xml = "".join(
        f"<item><title>{e(a['name'][:90])} – {nf(a['price'])} din (−{round((1 - a['price'] / a['low30']) * 100)}%, {e(a['store'])})</title>"
        f"<link>{BASE}/{(a['path'] + '?utm_source=rss') if a.get('path') else ('?utm_source=rss#a=' + a['id'])}</link><guid isPermaLink=\"false\">{a['id']}-{a['price']}</guid>"
        f"<description>{e(why(a))}</description><pubDate>{dt.datetime.now(dt.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>" for a in top_deals(arts, today, 20))
    (site / "rss.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>babl cene – stvarna sniženja</title>'
                                  f'<link>{BASE}/</link><description>Najveći stvarni popusti u Srbiji, svakog dana.</description><language>sr</language>{items_xml}</channel></rss>', encoding="utf-8")
    (site / "top10.json").write_text(json.dumps([{k: a[k] for k in ("store", "name", "price", "low30", "url", "id")} | {"path": a.get("path", "")} for a in top], ensure_ascii=False), encoding="utf-8")

    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{e(u)}</loc><lastmod>{d}</lastmod></url>" for u, d in urls] + ["</urlset>"]
    (site / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")
    (site / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    log(f"seo pages: {len(pick)} articles, {len(cats)} categories, {len(bystore)} stores, sitemap {len(urls)} URLs")
    return len(urls)

if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "site")
