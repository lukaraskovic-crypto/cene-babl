"""
Search-engine pages for cene.babl.cc, written next to the website after every build (also in "site" mode):

    p/<name>-<id>.html     one page per article worth finding (confirmed reductions, other advertised discounts, price drops)
    k/<category>.html      category pages (confirmed reductions first, then the cheapest)
    prodavnica/<store>.html, popusti.html, crni-petak.html, podaci.html (+ podaci.csv/json, data for journalists: press.py)
    sitemap.xml, robots.txt, seo.css

Every page is plain HTML (readable without JavaScript) and links to the live site (/#a=<id>) for the full tool.
    python seo.py site        # rebuild the pages from site/data*.js

Languages: Serbian (Latin) at the root, every other language under /<code>/ (en, cir = Serbian Cyrillic, hu, ru, uk, sk, ro, rue, sq, bs, hr,
bg, mk, rom, zh, tr, ar, fa). Texts come from i18n/<code>.json (machine-translated except sr/en; cir is transliterated from sr).
Other languages get the hub pages, all store pages, the biggest categories and the top articles (config: seo_pages_other, seo_cats_other).
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


# ------------------------------------------------------------------ languages
HERE = Path(__file__).resolve().parent
LANGS = ["sr", "en", "cir", "hu", "ru", "uk", "sk", "ro", "rue", "sq", "bs", "hr", "bg", "mk", "rom", "zh", "tr", "ar", "fa"]
NATIVE = {"sr": "Srpski", "en": "English", "cir": "Ћирилица", "hu": "Magyar", "ru": "Русский", "uk": "Українська", "sk": "Slovenčina", "ro": "Română",
          "rue": "Руски", "sq": "Shqip", "bs": "Bosanski", "hr": "Hrvatski", "bg": "Български", "mk": "Македонски", "rom": "Romani", "zh": "中文",
          "tr": "Türkçe", "ar": "العربية", "fa": "فارسی"}
HREFLANG = {"sr": "sr-Latn", "cir": "sr-Cyrl"}
OGLOC = {"sr": "sr_RS", "cir": "sr_RS", "en": "en_GB", "hu": "hu_HU", "ru": "ru_RU", "uk": "uk_UA", "sk": "sk_SK", "ro": "ro_RO", "sq": "sq_AL", "bs": "bs_BA",
         "hr": "hr_HR", "bg": "bg_BG", "mk": "mk_MK", "zh": "zh_CN", "tr": "tr_TR", "ar": "ar_AR", "fa": "fa_IR"}
RTL = {"ar", "fa"}

_C1 = dict(zip("abvgdđežzijklmnoprstćufhcčšABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠ", "абвгдђежзијклмнопрстћуфхцчшАБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ"))
_C2 = {"lj": "љ", "nj": "њ", "dž": "џ", "Lj": "Љ", "Nj": "Њ", "Dž": "Џ", "LJ": "Љ", "NJ": "Њ", "DŽ": "Џ"}
_KEEP = re.compile(r"^(babl|cene\.babl\.cc|pametno\.rs|Gigatron|WinWin|Big|Bang|Ananas|PC|Practic|Eurotehna|Tehnomedia|Tehnomanija|Google|Instagram|Viber|iPad|Air|Max|Xiaomi|OLED\w*|e-mail|email|Top)$", re.I)
def _cw(w):
    if _KEEP.match(w) or re.search(r"\d", w) or re.search(r"[qwxy]", w, re.I) or (len(w) > 1 and w == w.upper()): return w
    o, i = "", 0
    while i < len(w):
        if w[i:i + 2] in _C2: o += _C2[w[i:i + 2]]; i += 2; continue
        o += _C1.get(w[i], w[i]); i += 1
    return o
def cyr(s):
    """Serbian Latin → Cyrillic for running text; tags, {placeholders}, entities, URLs and brand/model words stay as they are."""
    parts = re.split(r"(<[^>]*>|\{\w+\}|&[a-z#0-9]+;|https?://\S+|babl cene|e-mail|B-roba)", str(s))
    return "".join(p if i % 2 else re.sub(r"[A-Za-z0-9ČĆŽŠĐčćžšđ]+(?:\.[A-Za-z]+)*", lambda m: _cw(m.group(0)), p) for i, p in enumerate(parts))
def _deep(o, f): return f(o) if isinstance(o, str) else [_deep(x, f) for x in o] if isinstance(o, list) else {k: _deep(v, f) for k, v in o.items()} if isinstance(o, dict) else o
def _merge(base, o):
    if not isinstance(base, dict) or not isinstance(o, dict): return base if o is None else o
    return {k: _merge(base.get(k), o.get(k)) if k in o else base[k] for k in base}

_TEXT = {}
def texts():
    """{lang: {"seo": {...}, "mail": {...}}} for every language with a text file (English fills gaps)."""
    if _TEXT: return _TEXT
    rd = lambda c: json.loads((HERE / "i18n" / f"{c}.json").read_text(encoding="utf-8"))
    en = rd("en"); _TEXT["sr"] = rd("sr"); _TEXT["en"] = en; _TEXT["cir"] = _deep(_TEXT["sr"], cyr)
    for c in LANGS:
        if c in _TEXT: continue
        try: _TEXT[c] = _merge(en, rd(c))
        except Exception: pass
    return _TEXT

pre = lambda l: "" if l == "sr" else l + "/"
home = lambda l: "/" if l == "sr" else f"/?lang={l}"
app = lambda l, aid: ("/" if l == "sr" else f"/?lang={l}") + f"#a={aid}"
F = lambda s, **k: s.format(**k)

def dfmt(S, d): return F(S["date"], d=d.day, m=S["months"][d.month - 1], y=d.year)
def dshort(S, d): return f"{d.day}. {S['months'][d.month - 1]}" if "{d}." in S["date"] else F(S["date"], d=d.day, m=S["months"][d.month - 1], y="").strip(" ,.年")

def why(a, S):
    g, l = a["g"], (nf(a["low30"]) + " " + S["cur"] if a["low30"] else "")
    pc = lambda x: f"{round(x * 100)}%"
    if g == "real" and a["low30"]: return F(S["why_real"], p=pc(1 - a["price"] / a["low30"]), l=l)
    if g == "raised" and a["low30"]: return F(S["why_raised"], c=pc(a["claimed"]), p=pc(a["price"] / a["low30"] - 1), l=l)
    if g == "fake" and a["low30"]: return F(S["why_fake"], c=pc(a["claimed"]), l=l)
    if g == "nochange" and a["low30"]: return F(S["why_nochange"], l=l)
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

def svg(hist, S):
    if len(hist) < 2: return ""
    ps = [p for _, p in hist]; mn, mx = min(ps) * 0.97, max(ps) * 1.03; W, H, L, B = 640, 180, 64, 22
    x = lambda i: L + i / (len(hist) - 1) * (W - L - 8); y = lambda p: H - B - (p - mn) / ((mx - mn) or 1) * (H - B - 8)
    d = f"M{x(0):.1f},{y(hist[0][1]):.1f}" + "".join(f" H{x(i):.1f} V{y(hist[i][1]):.1f}" for i in range(1, len(hist)))
    grid = "".join(f'<text x="0" y="{y(v) + 4:.1f}">{nf(v)}</text><line x1="{L}" x2="{W}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>' for v in (mn, (mn + mx) / 2, mx))
    a, b = dshort(S, hist[0][0]), dshort(S, hist[-1][0])
    return (f'<svg class="ch" viewBox="0 0 {W} {H}" role="img" aria-label="{e(F(S["chart_aria"], a=a, b=b))}" direction="ltr">{grid}'
            f'<path d="{d}"/><text x="{L}" y="{H - 4}">{e(a)}</text><text x="{W - 8}" y="{H - 4}" text-anchor="end">{e(b)}</text></svg>')

CSS = """:root{--bg:#F6F7F3;--s:#fff;--t:#13201A;--m:#5B6B62;--p:#1F6B45;--b:#DCE3DD;--good:#1F6B45;--goodbg:#E3F3EA;--bad:#B3261E;--badbg:#FBEAE8;--warn:#8A5A00;--warnbg:#FBF1DC}
@media (prefers-color-scheme:dark){:root{--bg:#0E1512;--s:#17211C;--t:#E8F0EA;--m:#9AACA1;--p:#5CC48A;--b:#28362E;--good:#5CC48A;--goodbg:#173326;--bad:#F2B8B5;--badbg:#3A1D1B;--warn:#E8C27A;--warnbg:#33290F}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--p)}.w{max-width:880px;margin:0 auto;padding:0 16px}header{background:var(--s);border-bottom:1px solid var(--b)}
header .w{display:flex;align-items:center;flex-wrap:wrap;gap:4px 14px;min-height:56px;padding-top:8px;padding-bottom:8px}.wm{font-weight:800;font-size:20px;color:var(--t);text-decoration:none;white-space:nowrap}.wm b{color:var(--p)}
header nav{margin-left:auto;display:flex;flex-wrap:wrap;gap:4px 14px;font-size:14px}header nav a{white-space:nowrap}main{padding:22px 0 40px}.bc{font-size:13px;color:var(--m)}.bc a{color:var(--m)}
h1{font-size:26px;line-height:1.25;margin:8px 0 12px}h2{font-size:18px;margin:28px 0 10px}.pr{font-size:34px;font-weight:800;color:var(--p)}.was{color:var(--m);text-decoration:line-through;margin-left:10px}
.tag{display:inline-block;font-size:13px;font-weight:700;border-radius:99px;padding:3px 10px;margin:6px 6px 0 0}.good{color:var(--good);background:var(--goodbg)}.bad{color:var(--bad);background:var(--badbg)}.warn{color:var(--warn);background:var(--warnbg)}
.box{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:14px 16px;margin:14px 0}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0}dt{font-size:13px;color:var(--m)}dd{margin:0;font-weight:700}
.btn{display:inline-block;padding:9px 16px;border-radius:99px;border:1px solid var(--b);background:var(--s);text-decoration:none;font-weight:700;margin:6px 8px 0 0}.btn.pri{background:var(--p);color:var(--s);border-color:var(--p)}
.ch{width:100%;height:auto}.ch path{fill:none;stroke:var(--p);stroke-width:2.4}.ch line{stroke:var(--b)}.ch text{font-size:11px;fill:var(--m)}
.l{list-style:none;padding:0;margin:0;counter-reset:n}.l li{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:10px 14px;margin:8px 0;display:flex;gap:12px;justify-content:space-between;align-items:baseline}
.l li>div:first-child{min-width:0;overflow-wrap:anywhere}.l .n{font-weight:600}.l .m{font-size:13px;color:var(--m)}.l .p{font-weight:800;white-space:nowrap;text-align:right}.l .p .m{display:block}ol.l li{counter-increment:n}ol.l li::before{content:counter(n);flex:none;align-self:center;font-weight:800;color:var(--p);min-width:1.4em}.cl{columns:2 220px;font-size:15px}.cl a{display:block;padding:2px 0}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--b);padding:6px 4px;text-align:left}footer{border-top:1px solid var(--b);color:var(--m);font-size:13px;padding:18px 0 40px}.lg{margin-top:10px;line-height:1.9}.lg a{margin-right:10px;white-space:nowrap}[dir=rtl] .was{margin-left:0;margin-right:10px}[dir=rtl] .l .p{text-align:left}[dir=rtl] .pr,[dir=rtl] .p{direction:ltr;unicode-bidi:isolate}"""

# anonymous page-view log for these static pages (same rules as the main site: no cookies, no IPs, no persistent id; DNT/GPC respected)
TJS = r"""(()=>{ try{ if(!/babl\.cc$/.test(location.hostname)||localStorage.getItem('notrack')==='1'||navigator.doNotTrack==='1'||navigator.globalPrivacyControl) return; }catch(e){ return; }
let sid=''; try{ sid=sessionStorage.getItem('sid')||''; }catch(e){}
if(!sid){ sid=(Math.random().toString(36).slice(2)+Date.now().toString(36)).replace(/[^a-z0-9]/g,'').slice(0,24); try{ sessionStorage.setItem('sid',sid); }catch(e){} }
let ref=''; try{ ref=document.referrer?new URL(document.referrer).hostname:''; }catch(e){}
const LP=location.pathname.match(/^\/(en|cir|hu|ru|uk|sk|ro|rue|sq|bs|hr|bg|mk|rom|zh|tr|ar|fa)\//), pth=LP?location.pathname.slice(LP[0].length-1):location.pathname, kind=pth.startsWith('/p/')?'p':pth.startsWith('/k/')?'k':pth.startsWith('/prodavnica/')?'store':pth.replace(/^\/|\.html$/g,'')||'home';
let fs=null; try{ fs=localStorage.getItem('fs'); if(!fs) localStorage.setItem('fs',new Date().toISOString().slice(0,10)); }catch(e){}
const send=rows=>{ try{ fetch('https://hxtdrtsqigvuvhaszxna.supabase.co/rest/v1/rpc/log_events',{method:'POST',keepalive:true,headers:{apikey:'sb_publishable_DPAXHrrEuhxB1ABfXQ7UrQ_azF6yuZ5','Content-Type':'application/json'},body:JSON.stringify({rows})}).catch(()=>{}); }catch(e){} };
const m=matchMedia('(max-width:760px)').matches, t0=Date.now();
send([{sid,ev:'page',q:pth.slice(0,120),ref:ref||'direct',lang:LP?LP[1]:'sr',mobile:m,item:(document.querySelector('h1')||{}).textContent?.slice(0,150),data:{kind,new:!fs}}]);
let done=false; const leave=()=>{ if(done) return; done=true; send([{sid,ev:'leave',q:pth.slice(0,120),lang:'sr',mobile:m,data:{sec:Math.min(3600,Math.round((Date.now()-t0)/1000)),kind}}]); };
addEventListener('pagehide',leave); addEventListener('visibilitychange',()=>{ if(document.visibilityState==='hidden') leave(); });
document.addEventListener('click',e=>{ const a=e.target.closest('a[href^="http"]'); if(!a) return; let h=''; try{ h=new URL(a.href).hostname; }catch(_){}
  if(h&&!/babl\.cc$/.test(h)) send([{sid,ev:'out',store:h.replace(/^www\./,''),item:(document.querySelector('h1')||{}).textContent?.slice(0,150),lang:'sr',mobile:m,data:{from:kind}}]); },true); })();"""


VCLS = {"real": "good", "raised": "bad", "fake": "bad", "nochange": "warn"}

def page(l, S, title, desc, path, body, crumbs=(), ld=None, og_type="website", alts=()):
    """path is relative to the language root (e.g. "p/x.html"); alts = the languages that also have this page."""
    url = BASE + "/" + pre(l) + path
    bc = (f'<div class="bc"><a href="{home(l)}">babl cene</a>' + "".join(f' › <a href="{e(h)}">{e(t)}</a>' if h else f" › {e(t)}" for t, h in crumbs) + "</div>") if crumbs else ""
    lds = [ld] if ld else []
    if crumbs:
        items = [{"@type": "ListItem", "position": 1, "name": "babl cene", "item": BASE + "/" + pre(l)}]
        for k, (t, h) in enumerate(crumbs, 2): items.append({"@type": "ListItem", "position": k, "name": t, **({"item": BASE + h} if h else {})})
        lds.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items})
    ldh = "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False).replace("</", "<\\/") + "</script>" for x in lds)
    alts = [a for a in LANGS if a in set(alts) | {l}]
    hl = "".join(f'<link rel="alternate" hreflang="{HREFLANG.get(a, a)}" href="{BASE}/{pre(a)}{path}">' for a in alts) + (f'<link rel="alternate" hreflang="x-default" href="{BASE}/{path}">' if "sr" in alts else "")
    sw = '<div class="lg">' + e(S["lang"]) + ": " + "".join(f'<a href="/{pre(a)}{path}" lang="{HREFLANG.get(a, a)}"{" aria-current=page" if a == l else ""}>{e(NATIVE[a])}</a> ' for a in alts) + "</div>" if len(alts) > 1 else ""
    p = pre(l)
    return f"""<!doctype html><html lang="{HREFLANG.get(l, l)}" dir="{'rtl' if l in RTL else 'ltr'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{e(url)}">{hl}
<meta property="og:type" content="{og_type}"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(url)}"><meta property="og:site_name" content="babl cene"><meta property="og:locale" content="{OGLOC.get(l, 'sr_RS')}">
<meta name="theme-color" content="#1F6B45"><link rel="alternate" type="application/rss+xml" title="babl cene" href="/rss.xml"><link rel="stylesheet" href="/seo.css">{ldh}<script defer src="/t.js"></script></head><body>
<header><div class="w"><a class="wm" href="{home(l)}" dir="ltr">babl <b>cene</b></a><nav><a href="/{p}top10.html">{e(S["nav_top10"])}</a><a href="/{p}popusti.html">{e(S["nav_real"])}</a><a href="/{p}crni-petak.html">{e(S["nav_bf"])}</a></nav></div></header>
<main class="w">{bc}{body}</main><footer class="w">{e(S["note"])}{(" " + e(S["auto"])) if S.get("auto") else ""} <a href="{home(l)}">{e(S["foot_search"])}</a> · <a href="/sitemap.xml">{e(S["foot_sitemap"])}</a>{(' · <a href="/' + p + 'podaci.html">' + e(S["foot_press"]) + "</a>") if l in ("sr", "en") else ""}{sw}</footer></body></html>"""

def li(a, l, S, own=None):
    """own: the set of article ids that have a page in this language (others link to the live site)."""
    tag = f' <span class="tag {VCLS[a["g"]]}">{e(S["verdict"][a["g"]])}</span>' if a["g"] in VCLS else ""
    has = a.get("path") and (own is None or a["id"] in own)
    nm = f'<a href="/{pre(l)}{a["path"]}">{e(a["name"])}</a>' if has else f'<a href="{app(l, a["id"])}">{e(a["name"])}</a>'
    old = f' <s>{nf(a["old"])}</s>' if a["old"] > a["price"] else ""
    return f'<li><div><div class="n">{nm}</div><div class="m">{e(a["store"])}{(" · " + e(a["cat"])) if a["cat"] else ""}{tag}</div></div><div class="p">{nf(a["price"])} {e(S["cur"])}<span class="m">{old}</span></div></li>'

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
    try: CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    except Exception: CFG = {}
    N_ART, N_CAT = int(CFG.get("seo_pages_other", 300)), int(CFG.get("seo_cats_other", 120))
    TX = texts(); langs = [l for l in LANGS if l in TX]
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
    pri = lambda a: (0 if a["g"] == "real" else 1 if a["g"] in VCLS else 2, -a["drop"], -a["price"])
    pick = sorted([a for a in arts if a["price"] >= 3000 and (a["g"] in VCLS or a["drop"] >= 0.05)], key=pri)[:MAX_PAGES]
    for a in pick: a["path"] = f"p/{slug(a['name'])}-{a['id']}.html"
    bycat = {}
    for a in arts:
        if a["cat"]: bycat.setdefault(slug(a["cat"], 60), []).append(a)
    cats = {k: v for k, v in bycat.items() if len(v) >= 15}
    catname = {k: max({a["cat"] for a in v}, key=lambda c: (sum(1 for a in v if a["cat"] == c), c != fold(c))) for k, v in cats.items()}
    bystore = {}
    for a in arts: bystore.setdefault(a["store"], []).append(a)
    # what each language gets
    ART = {l: (pick if l == "sr" else pick[:N_ART]) for l in langs}
    OWN = {l: {a["id"] for a in ART[l]} for l in langs}
    big = sorted(cats, key=lambda k: -len(cats[k]))
    CAT = {l: (list(cats) if l == "sr" else big[:N_CAT]) for l in langs}
    alt_art = lambda aid: [l for l in langs if aid in OWN[l]]
    alt_cat = lambda k: [l for l in langs if k in CAT[l]]

    # clean old pages, write new ones
    import shutil
    for l in LANGS:
        if l == "sr": continue
        if (site / l).is_dir(): shutil.rmtree(site / l)
    for d in ("p", "k", "prodavnica"):
        (site / d).mkdir(parents=True, exist_ok=True)
        for f in (site / d).glob("*.html"): f.unlink()
    (site / "seo.css").write_text(CSS, encoding="utf-8")
    (site / "t.js").write_text(TJS, encoding="utf-8")
    for f in (HERE / "static").glob("*"): shutil.copy(f, site / f.name)
    (site / "i18n").mkdir(exist_ok=True)
    for f in (HERE / "i18n").glob("*.js"):
        if f.name != "validate.js": shutil.copy(f, site / "i18n" / f.name)
    (site / "manifest.webmanifest").write_text(json.dumps({"name": "babl cene – provera popusta", "short_name": "babl cene", "start_url": "/?utm_source=pwa",
        "display": "standalone", "background_color": "#F6F7F3", "theme_color": "#1F6B45", "lang": "sr",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}, {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}, ensure_ascii=False), encoding="utf-8")
    urls = [(BASE + "/", data["date"])]
    def W(l, path, s):
        f = site / (pre(l) + path); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(s, encoding="utf-8"); urls.append((BASE + "/" + pre(l) + path, data["date"]))
    bf = dt.date(today.year, 11, 1); bf += dt.timedelta(days=(4 - bf.weekday()) % 7 + 21)       # 4th Friday of November
    real_all = sorted([a for a in arts if a["g"] == "real" and a["low30"]], key=lambda a: a["price"] / a["low30"])
    top = top_deals(arts, today, 10)
    n_pages = 0

    for l in langs:
        S = TX[l]["seo"]; p = pre(l); own = OWN[l]; cur = S["cur"]; L_ = lambda a: li(a, l, S, own)
        for a in ART[l]:
            ck = slug(a["cat"], 60) if a["cat"] else ""
            hist = year_dates(a["hist"], today); hp = [x for _, x in hist] + [a["price"]]
            same = [b for b in cats.get(ck, []) if b is not a and b.get("path")][:8] if ck in cats else []
            w = why(a, S)
            tag = f'<span class="tag {VCLS[a["g"]]}">{e(S["verdict"][a["g"]])}</span>' if a["g"] in VCLS else ""
            fig = [(S["art_crossed"], nf(a["old"]) + " " + cur if a["old"] > a["price"] else "–"), (S["art_low"], nf(a["low30"]) + " " + cur if a["low30"] else "–"),
                   (S["art_min"], nf(min(hp)) + " " + cur if len(hp) > 1 else "–"), (S["art_xs"], f"{nf(a['xs'])} {cur} ({e(a['xss'])})" if a["xs"] else "–")]
            spec = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in list(a["specs"].items())[:12])
            tbl = "".join(f"<tr><td>{e(dfmt(S, d))}</td><td>{nf(x)} {e(cur)}</td></tr>" for d, x in reversed(hist[-12:]))
            catl = f"/{p}k/{ck}.html" if ck in CAT[l] else (f"/k/{ck}.html" if ck in cats else "")
            body = (f"<h1>{e(a['name'])}</h1><div>{e(a['store'])}{(' · ' + e(a['cat'])) if a['cat'] else ''}</div>"
                    f'<div style="margin:12px 0"><span class="pr">{nf(a["price"])} {e(cur)}</span>'
                    + (f'<span class="was">{nf(a["old"])} {e(cur)}</span> <b style="color:var(--bad)">−{round(a["claimed"] * 100)}%</b>' if a["claimed"] else "") + f"<br>{tag}</div>"
                    + (f'<div class="box"><b>{e(S["art_why"])}</b><br>{e(w)}</div>' if w else "")
                    + '<div class="box"><dl>' + "".join(f"<div><dt>{e(k)}</dt><dd>{v}</dd></div>" for k, v in fig) + "</dl></div>"
                    + f'<p><a class="btn pri" href="{app(l, a["id"])}">{e(S["art_track"])}</a>' + (f'<a class="btn" href="{e(a["url"])}" rel="nofollow noopener" target="_blank">{e(S["art_shop"])}</a>' if a["url"] else "") + "</p>"
                    + (f"<h2>{e(S['art_hist'])}</h2>{svg(hist, S)}<table>{tbl}</table>" if len(hist) > 1 else "")
                    + (f"<h2>{e(S['art_spec'])}</h2><table>{spec}</table>" if spec else "")
                    + (f'<h2>{e(F(S["art_similar"], cat=a["cat"]))}</h2><ul class="l">' + "".join(L_(b) for b in same) + "</ul>"
                       + (f'<p><a href="{catl}">{e(F(S["art_allcat"], cat=a["cat"]))}</a></p>' if catl else "") if same else "")
                    + f'<p class="bc">{e(F(S["art_updated"], d=upd))}</p>')
            title = F(S["art_title"], name=a["name"][:70], price=nf(a["price"]), store=a["store"])
            desc = (F(S["art_desc"], name=a["name"][:90], price=nf(a["price"]), store=a["store"]) + " " + (S["verdict"][a["g"]] + ". " if a["g"] in VCLS else "")
                    + (F(S["art_desc_low"], low=nf(a["low30"])) + " " if a["low30"] else "") + S["art_desc_end"])[:300]
            ld = {"@context": "https://schema.org", "@type": "Product", "name": a["name"], "category": a["cat"] or None, "url": BASE + "/" + p + a["path"],
                  "offers": {"@type": "Offer", "price": a["price"], "priceCurrency": "RSD", "availability": "https://schema.org/InStock",
                             "url": a["url"] or BASE + "/" + p + a["path"], "seller": {"@type": "Organization", "name": a["store"]}}}
            ld = {k: v for k, v in ld.items() if v is not None}
            crumbs = ([(a["cat"], catl)] if catl else []) + [(a["name"][:60], "")]
            W(l, a["path"], page(l, S, title, desc, a["path"], body, crumbs, ld, "product", alt_art(a["id"])))

        for k in CAT[l]:
            v = cats[k]; nm = catname[k]
            real = sorted([a for a in v if a["g"] == "real"], key=lambda a: a["price"] / (a["low30"] or a["price"]))[:30]
            cheap = sorted([a for a in v if a["g"] != "real"], key=lambda a: a["price"])[:40]
            stores = sorted({a["store"] for a in v})
            body = (f"<h1>{e(F(S['cat_h1'], cat=nm))}</h1><p>{e(F(S['cat_intro'], n=nf(len(v)), stores=', '.join(stores)))}</p>"
                    + (f'<h2>{e(F(S["cat_real"], n=len(real)))}</h2><ul class="l">' + "".join(L_(a) for a in real) + "</ul>" if real else "")
                    + f'<h2>{e(S["cat_cheap"])}</h2><ul class="l">' + "".join(L_(a) for a in cheap) + "</ul>"
                    + f'<p><a class="btn pri" href="{home(l)}#q={e(nm)}">{e(F(S["cat_search"], cat=nm))}</a></p>')
            desc = F(S["cat_desc"], cat=nm, n=nf(len(v))) + " " + (F(S["cat_desc_real"], r=len(real)) + " " if real else "") + S["cat_desc_end"]
            W(l, f"k/{k}.html", page(l, S, F(S["cat_title"], cat=nm), desc[:300], f"k/{k}.html", body, [(nm, "")], alts=alt_cat(k)))

        for s_, v in bystore.items():
            real = sorted([a for a in v if a["g"] == "real"], key=lambda a: a["price"] / (a["low30"] or a["price"]))[:40]
            flag = [a for a in v if a["g"] in ("fake", "raised")]
            sc = sorted({slug(a["cat"], 60) for a in v if a["cat"] and slug(a["cat"], 60) in CAT[l]})
            body = (f"<h1>{e(F(S['store_h1'], store=s_))}</h1><p>{e(F(S['store_intro'], store=s_, n=nf(len(v)), r=len(real), f=len(flag)))}</p>"
                    + (f'<h2>{e(S["store_real"])}</h2><ul class="l">' + "".join(L_(a) for a in real) + "</ul>" if real else "")
                    + (f'<h2>{e(S["store_cats"])}</h2><div class="cl">' + "".join(f'<a href="/{p}k/{c}.html">{e(catname[c])}</a>' for c in sc) + "</div>" if sc else ""))
            p_ = f"prodavnica/{slug(s_)}.html"
            W(l, p_, page(l, S, F(S["store_title"], store=s_), F(S["store_desc"], store=s_, r=len(real), n=nf(len(v))), p_, body, [(s_, "")], alts=langs))

        body = (f"<h1>{e(S['real_h1'])}</h1><p>{e(F(S['real_intro'], n=nf(len(real_all)), d=upd))}</p><ul class='l'>" + "".join(L_(a) for a in real_all[:120]) + "</ul>"
                + f'<h2>{e(S["real_bycat"])}</h2><div class="cl">' + "".join(f'<a href="/{p}k/{k}.html">{e(catname[k])}</a>' for k in big if k in CAT[l][:80] or (l == "sr" and k in big[:80])) + "</div>"
                + f'<h2>{e(S["real_bystore"])}</h2><div class="cl">' + "".join(f'<a href="/{p}prodavnica/{slug(s_)}.html">{e(s_)}</a>' for s_ in sorted(bystore)) + "</div>")
        W(l, "popusti.html", page(l, S, F(S["real_title"], n=nf(len(real_all))), F(S["real_desc"], n=nf(len(real_all))), "popusti.html", body, [(S["nav_real"], "")], alts=langs))

        body = (f"<h1>{e(F(S['bf_h1'], y=today.year))}</h1><p>{F(S['bf_p'], d=bf.day, y=bf.year)}</p>"
                f'<div class="box"><b>{e(S["bf_box"])}</b><ol>' + "".join(f"<li>{F(x, home=home(l))}</li>" if "{home}" in x else f"<li>{x}</li>" for x in S["bf_steps"]) + "</ol></div>"
                f"<h2>{e(S['bf_top'])}</h2><ul class='l'>" + "".join(L_(a) for a in real_all[:60]) + "</ul>"
                f'<p><a class="btn pri" href="/{p}popusti.html">{e(S["bf_all"])}</a><a class="btn" href="{home(l)}">{e(S["bf_search"])}</a></p>')
        W(l, "crni-petak.html", page(l, S, F(S["bf_title"], y=today.year), F(S["bf_desc"], y=today.year), "crni-petak.html", body, [(F(S["bf_crumb"], y=today.year), "")], alts=langs))

        body = (f"<h1>{e(S['top_h1'])}</h1><p>{e(F(S['top_intro'], d=upd))}</p><ol class='l' style='padding:0'>" + "".join(L_(a) for a in top) + "</ol>"
                f"<p><a class='btn pri' href='/{p}popusti.html'>{e(S['top_all'])}</a></p>")
        W(l, "top10.html", page(l, S, S["top_title"], S["top_desc"], "top10.html", body, [(S["top_crumb"], "")], alts=langs))
        n_pages += len(ART[l]) + len(CAT[l]) + len(bystore) + 3

    # RSS (Serbian) + the data for the owner's morning e-mail
    S = TX["sr"]["seo"]
    items_xml = "".join(
        f"<item><title>{e(a['name'][:90])} – {nf(a['price'])} din (−{round((1 - a['price'] / a['low30']) * 100)}%, {e(a['store'])})</title>"
        f"<link>{BASE}/{(a['path'] + '?utm_source=rss') if a.get('path') else ('?utm_source=rss#a=' + a['id'])}</link><guid isPermaLink=\"false\">{a['id']}-{a['price']}</guid>"
        f"<description>{e(why(a, S))}</description><pubDate>{dt.datetime.now(dt.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>" for a in top_deals(arts, today, 20))
    (site / "rss.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{e(S["rss_title"])}</title>'
                                  f'<link>{BASE}/</link><description>{e(S["rss_desc"])}</description><language>sr</language>{items_xml}</channel></rss>', encoding="utf-8")
    (site / "top10.json").write_text(json.dumps([{k: a[k] for k in ("store", "name", "price", "low30", "url", "id")} | {"path": a.get("path", "")} for a in top], ensure_ascii=False), encoding="utf-8")

    try:       # "data for journalists" page (podaci.html, en/podaci.html, podaci.csv/json); see press.py
        sys.path.insert(0, str(HERE)); import press; press.pages(site, W, log)
    except Exception as ex: log(f"press page skipped: {ex!r}")
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{e(u)}</loc><lastmod>{d}</lastmod></url>" for u, d in urls] + ["</urlset>"]
    (site / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")
    (site / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    log(f"seo pages: {n_pages} in {len(langs)} languages ({len(pick)} articles in Serbian, {N_ART} in the others), {len(cats)} categories, {len(bystore)} stores, sitemap {len(urls)} URLs")
    return len(urls)

if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "site")
