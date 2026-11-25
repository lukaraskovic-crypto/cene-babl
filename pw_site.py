"""
Builds the website (site/index.html + data*.js + cats.js) after every run.
Serbian (latinica) by default, English toggle; works on phones; no server needed.

    python3 pw_site.py            # rebuild from the latest run folder
"""
import json, re, os, importlib.util, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
SITE = Path(os.environ.get("SITE_DIR", HERE / "site"))
REPO = os.environ.get("GITHUB_REPOSITORY", "lukaraskovic-crypto/cene-babl")
STORE_OF = {"gigatron": "Gigatron", "winwin": "WinWin", "tehnomanija": "Tehnomanija", "bigbang": "Big Bang", "ananas": "Ananas",
            "dotmarket": "DOTmarket", "bazzar": "Bazzar", "pcpractic": "PC Practic", "eurotehna": "Eurotehna", "tehnomedia": "Tehnomedia", "inelektronik": "Inelektronik"}

def _history(db_path, days=120):
    if not db_path.exists(): return {}, {}
    import importlib.util
    spec = importlib.util.spec_from_file_location("catalog", HERE / "catalog.py"); cat = importlib.util.module_from_spec(spec); spec.loader.exec_module(cat)
    h = cat.History(db_path)
    return h.series(days), h.meta()

# ---------------------------------------------------------------- the same product in different shops
CODE_JUNK = re.compile(r"^(\d+(GB|TB|MB|MAH|W|WH|L|BTU|KG|HZ|MHZ|GHZ|MM|CM|V|PA|K|MP|INCH|RPM|DB)|\d+GB\d+(GB|TB)?|\d+(GB|TB)?\d+(GB|TB)|\d+X\d+|(I[3579]|U[579]|R[3579]|C[357])\d+[A-Z]*|\d+|DDR\d.*|USB\d.*|WIFI\d*|PCIE\d*|RTX\d+|GTX\d+|RX\d+)$")
GENERIC = set("""LAPTOP NB NOTEBOOK SBS FRIZIDER FRIŽIDER KOMBINOVANI MASINA MAŠINA ZA PRANJE SUSENJE SUŠENJE SUDOVA VESA VEŠA TELEVIZOR TV SMART LED QLED OLED
MOBILNI TELEFON TABLET MONITOR GAMING GEJMING BEZICNI BEŽIČNI BEZICNE BEŽIČNE ZICNI ŽIČNI USISIVAC USISIVAČ ROBOT STAPNI ŠTAPNI APARAT KAFU ESPRESSO MIKSER UGRADNA UGRADNI
RERNA PLOCA PLOČA SPORET ŠPORET KLIMA UREDJAJ UREĐAJ INVERTER BOJLER SLUSALICE SLUŠALICE ZVUCNIK ZVUČNIK B-ROBA BROBA KUCISTE KUĆIŠTE STAMPAC ŠTAMPAČ RACUNAR RAČUNAR
DESKTOP PC ALL-IN-ONE AIO SET PAMETNI SAT NOVO NOVI NOVA REFURBISHED OUTLET MIKROTALASNA FRITEZA BLENDER PEGLA PARNA GREJALICA RADIJATOR PRECISCIVAC PREČIŠĆIVAČ
VAZDUHA ODVLAZIVAC ODVLAŽIVAČ KAMERA AKCIONA DRON KONZOLA IGRA SSD HDD MIS MIŠ TASTATURA PROJEKTOR SOUNDBAR ZAMRZIVAC ZAMRZIVAČ VINSKA VITRINA NAPA SUDOMASINA SUDOMAŠINA
KAFE APARATI DUAL INCH""".split())
def _brand(n):
    for t in re.findall(r"[A-Za-zČĆŽŠĐčćžšđ0-9-]+", n)[:4]:
        u = t.upper()
        if u in GENERIC or re.search(r"\d", u) or len(u) < 2: continue
        return u
    return ""
def _codes(n):     # model codes: letters + digits, at least 6 characters; "/" separates (i7/16/512GB/5060 is four specs, not a code)
    out = set()
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-.+]*", n):
        c = re.sub(r"[^A-Za-z0-9]", "", t).upper()
        if len(c) >= 6 and re.search(r"[A-Z]", c) and len(re.findall(r"\d", c)) >= 2 and not CODE_JUNK.match(c) \
                and not re.match(r"^\d+[A-Z]{1,4}$", c): out.add(c)          # "300TWS" (Wave/Live 300TWS), "55UHD": series words, not models
    return out

def match_groups(allit):
    """Group listings that are the same product: same model code (or one code = the other plus a short region/colour suffix,
    QE55Q80DATXXH ~ QE55Q80DAT), and no conflicting brand. Returns (group id per item, 0 = no match; cheapest offer at another shop)."""
    codes = [_codes(a["name"]) for a in allit]; brands = [_brand(a["name"]) for a in allit]
    full, pref = {}, {}
    for i, cs in enumerate(codes):
        for c in cs:
            full.setdefault(c, []).append(i)
            if len(c) >= 9:
                for L in range(max(8, len(c) - 4), len(c)): pref.setdefault(c[:L], []).append(i)
    par = list(range(len(allit)))
    def find(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    for i, cs in enumerate(codes):
        for c in cs:
            cand = list(full.get(c, ())) + list(pref.get(c, ()))
            for L in range(max(8, len(c) - 4), len(c)): cand += full.get(c[:L], ())
            if len(cand) > 60: continue                       # a code shared by that many listings is not a model code
            for j in cand:
                if j == i: continue
                if brands[i] and brands[j] and brands[i] != brands[j]: continue
                a, b = find(i), find(j)
                if a != b: par[a] = b
    roots = [find(i) for i in range(len(allit))]
    size = {}
    for r in roots: size[r] = size.get(r, 0) + 1
    gid, mg = {}, []
    for r in roots:
        if size[r] < 2 or size[r] > 80: mg.append(0); continue    # huge groups are chained mistakes – drop them
        mg.append(gid.setdefault(r, len(gid) + 1))
    by = {}
    for i, g in enumerate(mg):
        if g: by.setdefault(g, []).append(i)
    cheaper = []
    for i, a in enumerate(allit):
        g = mg[i]; best = None
        for j in by.get(g, ()):
            b = allit[j]
            if b["store"] != a["store"] and b["p"] and b["p"] >= a["p"] * 0.35 and (best is None or b["p"] < best[0]): best = (b["p"], b["store"])   # 3x cheaper = another product
        cheaper.append(best if best and best[0] < a["p"] else None)
    return mg, cheaper

def build(run_dir, date):
    run_dir = Path(run_dir)
    load = lambda n, d=None: json.loads((run_dir / n).read_text(encoding="utf-8")) if (run_dir / n).exists() else d
    items = load("items.json", [])
    allit = load("all_items.json", []) or items
    extra = load("site_extra.json", {})
    raw = load("raw.json", {}) or {}
    hist, meta = _history(HERE / "history.sqlite")
    ik = lambda x: (x["store"], x.get("u") or "") if x.get("u") and x["store"] != "Big Bang" else (x["store"], x["name"])
    promo = {ik(i): i for i in items}       # verdicts belong to one listing (URL), not to every listing with the same name
    try: pspecs = json.loads((HERE / "state" / "specs.json").read_text(encoding="utf-8"))   # specifications read from product pages
    except Exception: pspecs = {}

    groups, cheaper = match_groups(allit)     # same product across shops (and listings of one shop) by brand + model code
    short = lambda d: d[5:] if d else ""
    rows = []
    for n_, a in enumerate(allit):
        i = promo.get(ik(a), {})
        if i and i.get("p") != a["p"]: i = {}
        cheapest = cheaper[n_]
        key = f"{a['store']}|{a.get('u','')}|{a['name']}"
        h = hist.get(key, [])
        since, seen = (meta.get(key) or [date, date])
        rows.append([
            a["store"], a.get("cat", ""), a["name"], a["p"], a.get("o") or 0, i.get("l_used") or a.get("l") or 0,
            i.get("v", ""), i.get("mv", ""), (i.get("mkt") or 0), a.get("u", ""),
            cheapest[0] if cheapest and cheapest[1] != a["store"] else 0, cheapest[1] if cheapest and cheapest[1] != a["store"] else "",
            h[-60:], short(since), short(seen), a.get("nl") or 0, {k: v for k, v in (pspecs.get(a.get("u", "")) or {}).items() if not k.startswith("_")} or 0,
            groups[n_],
        ])
    now = dt.datetime.now(ZoneInfo("Europe/Belgrade"))
    data = {"date": date, "updated": now.strftime("%Y-%m-%d %H:%M"), "repo": REPO,
            "summary": extra.get("summary", []), "problems": extra.get("problems", []), "watch": extra.get("watch", []), "drops": extra.get("drops", []),
            "report": (run_dir / "report.txt").read_text(encoding="utf-8") if (run_dir / "report.txt").exists() else "",
            "cols": ["store", "cat", "name", "price", "old", "low30", "verdict", "market_verdict", "market_low", "url", "xs_price", "xs_store", "hist", "since", "seen", "listings", "specs", "mg"]}
    SITE.mkdir(parents=True, exist_ok=True)
    for old_ in SITE.glob("data*.js"): old_.unlink()
    rows_ = rows; CH = 15000
    parts = [rows_[k:k + CH] for k in range(0, len(rows_), CH)] or [[]]
    (SITE / "data.js").write_text("window.DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";window.DATA.rows=[];", encoding="utf-8")
    for k, part in enumerate(parts):
        (SITE / f"data-{k}.js").write_text("window.DATA.rows.push(..." + json.dumps(part, ensure_ascii=False, separators=(",", ":")) + ");", encoding="utf-8")
    # categories found by the full-catalogue crawl + what is currently excluded (for the owner's admin tab)
    try: excl = json.loads((HERE / "categories.json").read_text(encoding="utf-8")).get("exclude", {})
    except Exception: excl = {}
    cats = {STORE_OF[k[5:]]: v for k, v in raw.items() if k.startswith("cats_") and k[5:] in STORE_OF}
    (SITE / "cats.js").write_text("window.CATS=" + json.dumps({"found": cats, "exclude": excl}, ensure_ascii=False, separators=(",", ":")) + ";", encoding="utf-8")
    page = PAGE.replace("<!--DATA-->", '<script src="data.js"></script>' + "".join(f'<script src="data-{k}.js"></script>' for k in range(len(parts))) + '<script src="cats.js"></script>')
    (SITE / "index.html").write_text(page, encoding="utf-8")
    import shutil   # interface translations (loaded by the page on demand)
    (SITE / "i18n").mkdir(exist_ok=True)
    for f_ in (HERE / "i18n").glob("*.js"):
        if f_.name != "validate.js": shutil.copy(f_, SITE / "i18n" / f_.name)
    try:     # search-engine pages (p/, k/, prodavnica/, sitemap.xml) – never block the website itself
        sspec = importlib.util.spec_from_file_location("seo", HERE / "seo.py"); seo = importlib.util.module_from_spec(sspec); sspec.loader.exec_module(seo)
        seo.build(SITE)
    except Exception as e: print("seo pages failed:", e)
    return SITE / "index.html"

PAGE = (HERE / "site_template.html").read_text(encoding="utf-8") if (HERE / "site_template.html").exists() else ""

if __name__ == "__main__":
    runs = sorted((HERE / "runs").glob("20*"))
    if not runs: raise SystemExit("no runs yet")
    print(build(runs[-1], runs[-1].name))
