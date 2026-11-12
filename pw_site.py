"""
Builds the website (site/index.html + data*.js + cats.js) after every run.
Serbian (latinica) by default, English toggle; works on phones; no server needed.

    python3 pw_site.py            # rebuild from the latest run folder
"""
import json, re, os, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
SITE = Path(os.environ.get("SITE_DIR", HERE / "site"))
REPO = os.environ.get("GITHUB_REPOSITORY", "lukaraskovic-crypto/cene-babl")
STORE_OF = {"gigatron": "Gigatron", "winwin": "WinWin", "tehnomanija": "Tehnomanija", "bigbang": "Big Bang", "ananas": "Ananas",
            "dotmarket": "DOTmarket", "bazzar": "Bazzar", "pcpractic": "PC Practic", "eurotehna": "Eurotehna"}

def _history(db_path, days=120):
    if not db_path.exists(): return {}, {}
    import importlib.util
    spec = importlib.util.spec_from_file_location("catalog", HERE / "catalog.py"); cat = importlib.util.module_from_spec(spec); spec.loader.exec_module(cat)
    h = cat.History(db_path)
    return h.series(days), h.meta()

def build(run_dir, date):
    run_dir = Path(run_dir)
    load = lambda n, d=None: json.loads((run_dir / n).read_text(encoding="utf-8")) if (run_dir / n).exists() else d
    items = load("items.json", [])
    allit = load("all_items.json", []) or items
    extra = load("site_extra.json", {})
    raw = load("raw.json", {}) or {}
    hist, meta = _history(HERE / "history.sqlite")
    promo = {(i["store"], i["name"]): i for i in items}
    try: pspecs = json.loads((HERE / "state" / "specs.json").read_text(encoding="utf-8"))   # specifications read from product pages
    except Exception: pspecs = {}

    # cheapest price per model code across stores
    def keys(n):
        return {re.sub(r"[^A-Za-z0-9]", "", t).upper() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/.+]*", n)
                if len(re.sub(r"[^A-Za-z0-9]", "", t)) >= 6 and re.search(r"[A-Za-z]", t) and re.search(r"\d", t)}
    best = {}
    for a in allit:
        for k in keys(a["name"]):
            if k not in best or a["p"] < best[k][0]: best[k] = (a["p"], a["store"])

    short = lambda d: d[5:] if d else ""
    rows = []
    for a in allit:
        i = promo.get((a["store"], a["name"]), {})
        cheapest = min((best[k] for k in keys(a["name"]) if k in best), default=None)
        key = f"{a['store']}|{a.get('u','')}|{a['name']}"
        h = hist.get(key, [])
        since, seen = (meta.get(key) or [date, date])
        rows.append([
            a["store"], a.get("cat", ""), a["name"], a["p"], a.get("o") or 0, a.get("l") or i.get("l_used") or 0,
            i.get("v", ""), i.get("mv", ""), (i.get("mkt") or 0), a.get("u", ""),
            cheapest[0] if cheapest and cheapest[1] != a["store"] else 0, cheapest[1] if cheapest and cheapest[1] != a["store"] else "",
            h[-60:], short(since), short(seen), a.get("nl") or 0, pspecs.get(a.get("u", "")) or 0,
        ])
    now = dt.datetime.now(ZoneInfo("Europe/Belgrade"))
    data = {"date": date, "updated": now.strftime("%Y-%m-%d %H:%M"), "repo": REPO,
            "summary": extra.get("summary", []), "problems": extra.get("problems", []), "watch": extra.get("watch", []), "drops": extra.get("drops", []),
            "report": (run_dir / "report.txt").read_text(encoding="utf-8") if (run_dir / "report.txt").exists() else "",
            "cols": ["store", "cat", "name", "price", "old", "low30", "verdict", "market_verdict", "market_low", "url", "xs_price", "xs_store", "hist", "since", "seen", "listings", "specs"]}
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
    return SITE / "index.html"

PAGE = (HERE / "site_template.html").read_text(encoding="utf-8") if (HERE / "site_template.html").exists() else ""

if __name__ == "__main__":
    runs = sorted((HERE / "runs").glob("20*"))
    if not runs: raise SystemExit("no runs yet")
    print(build(runs[-1], runs[-1].name))
