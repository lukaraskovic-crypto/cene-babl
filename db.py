"""
Online database (Supabase / Postgres, via its REST API) – replaces Google Sheets and keeps the price history permanently.

Secrets (GitHub → Settings → Secrets → Actions):  SUPABASE_SERVICE_KEY  (the project's secret / service_role key)
URL comes from config.json "supabase_url" (or env SUPABASE_URL).  Without a key everything here is skipped.

Tables: price_points (every price change, per URL), articles (one row per article: first/last seen, current price, specs),
promos (daily verified promos), watch (G1–G4 rows), watch_terms, drops, store_summary, runs, meta, sheet_archive.

    python db.py restore history.sqlite     # rebuild the local SQLite history from the database (cache was lost)
    python db.py import-sheets              # one-time copy of the old Google Sheets (needs GOOGLE_SA_JSON)
"""
import json, os, sys, time, sqlite3, urllib.request, urllib.error, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
try: _CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
except Exception: _CFG = {}
URL = (os.environ.get("SUPABASE_URL") or _CFG.get("supabase_url") or "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY") or ""

def enabled(): return bool(URL and KEY)

def _req(method, path, body=None, headers=None, tries=5):
    h = {"apikey": KEY, "Content-Type": "application/json"}
    if KEY.startswith("eyJ"): h["Authorization"] = "Bearer " + KEY      # legacy JWT service_role key
    h.update(headers or {})
    data = None if body is None else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
    for k in range(tries):
        try:
            req = urllib.request.Request(URL + "/rest/v1/" + path, data=data, method=method, headers=h)
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = r.read().decode("utf-8")
                return (json.loads(txt) if txt else None), r.headers
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:400]
            if e.code in (408, 429, 500, 502, 503, 504) and k < tries - 1: time.sleep(3 * (k + 1)); continue
            raise RuntimeError(f"Supabase {method} {path.split('?')[0]}: HTTP {e.code} {msg}")
        except (urllib.error.URLError, TimeoutError) as e:
            if k < tries - 1: time.sleep(3 * (k + 1)); continue
            raise RuntimeError(f"Supabase {method} {path.split('?')[0]}: {e}")

def upsert(table, rows, keys, chunk=1000):
    """Insert or update rows (dicts). Rows with the same key are collapsed (last wins). Returns the number sent."""
    uniq = {}
    for r in rows: uniq[tuple(r.get(k) for k in keys)] = r
    rows = list(uniq.values())
    # PostgREST needs the same columns in every row of one request
    groups = {}
    for r in rows: groups.setdefault(tuple(sorted(r)), []).append(r)
    for cols, grp in groups.items():
        q = f"{table}?on_conflict={','.join(keys)}&columns={','.join(cols)}"
        for i in range(0, len(grp), chunk):
            _req("POST", q, grp[i:i + chunk], {"Prefer": "resolution=merge-duplicates,return=minimal"})
    return len(rows)

def select(table, query="", page=1000):
    out, off = [], 0
    while True:
        part, _ = _req("GET", f"{table}?{query}{'&' if query else ''}limit={page}&offset={off}")
        out += part or []
        if not part or len(part) < page: return out
        off += page

def meta_get(key):
    r = select("meta", "key=eq." + urllib.parse.quote(key))
    return r[0]["value"] if r else None

def meta_set(key, value): upsert("meta", [{"key": key, "value": str(value)}], ["key"])

# ---------------------------------------------------------------------------------------- price history
def push_history(sqlite_path, log=print):
    """Send every price point the database doesn't have yet (all of them the first time)."""
    db = sqlite3.connect(str(sqlite_path))
    since = meta_get("points_through") or "0000-00-00"
    rows = [dict(store=s, url=u or "", name=n, date=d, price=p, old=o, low30=l) for s, u, n, d, p, o, l in
            db.execute("SELECT store,url,name,date,price,old,low30 FROM points WHERE date>=?", (since,))]
    if rows:
        upsert("price_points", rows, ["store", "url", "name", "date"])
        meta_set("points_through", max(r["date"] for r in rows))
    log(f"database: {len(rows)} price points sent (since {since})")
    return len(rows)

def push_articles(all_items, date, full, hist_sqlite=None, specs=None, log=print):
    """articles table: current price, category, first/last seen, specs. Full runs send everything, refreshes only changes."""
    first = {}
    if hist_sqlite and Path(hist_sqlite).exists():
        for s, u, n, f in sqlite3.connect(str(hist_sqlite)).execute("SELECT store,url,name,first FROM seen"): first[(s, u or "", n)] = f
    specs = specs or {}
    rows = []
    for a in all_items:
        if not full and a.get("since") != date: continue        # refresh: only articles whose price changed today
        k = (a["store"], a.get("u") or "", a["name"])
        r = dict(store=k[0], url=k[1], name=k[2], cat=a.get("cat", "")[:200], first_seen=first.get(k, date), last_seen=date,
                 price=a["p"], old=a.get("o"), low30=a.get("l"))
        sp = specs.get(k[1])
        if sp: r["specs"] = sp
        rows.append(r)
    n = upsert("articles", rows, ["store", "url", "name"]) if rows else 0
    log(f"database: {n} articles sent ({'all' if full else 'changed only'})")

def push_run(date, mode, items, watch_rows, drop_rows, summ, cat_counts, report, problems, log=print):
    """Daily results: verified promos, watch rows, price drops, per-store summary, run report."""
    if mode == "full":
        upsert("promos", [dict(date=date, store=i["store"], name=i["name"], cat=i.get("cat", ""), price=i["p"], old=i.get("o"), claimed=i.get("claimed"),
                               low30=i.get("l_used") or i.get("l"), real_cut=i.get("real"), market_low=i.get("mkt") or None, verdict=i.get("v"),
                               market_verdict=i.get("mv"), url=i.get("u", "")) for i in items], ["date", "store", "name"])
        upsert("watch", [dict(date=date, grp=w[0][:2], store=w[1], name=w[2], spec=w[3], price=w[4], old=w[5] or None, low30=w[6] or None,
                              real_cut=w[7] if w[7] != "" else None, market_best=w[8] or None, market_store=w[9], market_verdict=w[11], url=w[12])
                         for w in watch_rows], ["date", "grp", "store", "name"])
        upsert("store_summary", [dict(date=date, store=s[0], articles=cat_counts.get(s[0], 0), promos=s[1], with_low30=s[3], real_cuts=s[4], fake=s[5],
                                      raised=s[6], avg_claimed=s[2] if s[2] != "" else None, avg_real=s[7] if s[7] != "" else None) for s in summ],
               ["date", "store"])
    upsert("drops", [dict(date=date, store=d[0], cat=d[1], name=d[2], price=d[3], last_price=d[4], url=d[9] or "") for d in drop_rows],
           ["date", "store", "name", "url"])
    _req("POST", "runs", [dict(date=date, mode=mode, articles=sum(cat_counts.values()), problems="; ".join(problems) or None, report=report)],
         {"Prefer": "return=minimal"})
    log(f"database: run saved ({len(items)} promos, {len(watch_rows)} watch rows, {len(drop_rows)} drops)")

def previous_real_cuts(date):
    """(store, name) of yesterday's real cuts – for the NEW marker in the report."""
    r = select("promos", f"select=date&date=lt.{date}&order=date.desc", page=1)[:1]
    if not r: return set()
    return {(x["store"], x["name"]) for x in select("promos", f"select=store,name,verdict&date=eq.{r[0]['date']}&verdict=like.REAL*")}

# ---------------------------------------------------------------------------------------- website usage
def usage_summary(hours=24):
    """Short text about the website's last `hours`: visitors, searches, most opened articles, clicks to shops."""
    import datetime as _d
    since = (_d.datetime.now(_d.timezone.utc) - _d.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = [e for e in select("events", f"select=sid,ev,tab,q,store,item,mobile,ref&ts=gte.{since}") if not e["sid"].startswith("testsession")]
    if not ev: return f"Website (last {hours} h): no visitors."
    from collections import Counter
    sids = {e["sid"] for e in ev}; mob = {e["sid"] for e in ev if e.get("mobile")}
    c = lambda key, kind, n=5: Counter((e.get(key) or "").strip().lower() if key == "q" else e.get(key) for e in ev if e["ev"] == kind and e.get(key)).most_common(n)
    fmt = lambda xs: ", ".join(f"{k} ({v})" for k, v in xs) or "–"
    refs = Counter(e.get("ref") for e in ev if e["ev"] == "visit" and e.get("ref")).most_common(4)
    return "\n".join([f"Website (last {hours} h): {len(sids)} visitors ({round(100 * len(mob) / len(sids))}% phone), "
                      f"{sum(e['ev'] == 'search' for e in ev)} searches, {sum(e['ev'] == 'item' for e in ev)} articles opened, "
                      f"{sum(e['ev'] == 'out' for e in ev)} clicks to shops",
                      "• Top searches: " + fmt(c("q", "search")),
                      "• Most opened: " + fmt([(k[:40], v) for k, v in c("item", "item")]),
                      "• Tabs: " + fmt(c("tab", "tab")),
                      "• Came from: " + fmt(refs)])

# ---------------------------------------------------------------------------------------- restore
def restore_history(path, log=print):
    """Rebuild history.sqlite from the database (used when the GitHub cache expired)."""
    pts = select("price_points", "select=store,url,name,date,price,old,low30&order=store,url,name,date")
    if not pts: log("database: no price points to restore"); return False
    arts = select("articles", "select=store,url,name,first_seen,last_seen")
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE IF NOT EXISTS points(store TEXT, url TEXT, name TEXT, date TEXT, price INTEGER, old INTEGER, low30 INTEGER, PRIMARY KEY(store, url, name, date))")
    db.execute("CREATE TABLE IF NOT EXISTS seen(store TEXT, url TEXT, name TEXT, first TEXT, last TEXT, PRIMARY KEY(store, url, name))")
    db.executemany("INSERT OR REPLACE INTO points VALUES(?,?,?,?,?,?,?)", [(p["store"], p["url"], p["name"], p["date"], p["price"], p["old"], p["low30"]) for p in pts])
    fl = {}
    for p in pts:
        k = (p["store"], p["url"], p["name"]); f, l = fl.get(k, (p["date"], p["date"])); fl[k] = (min(f, p["date"]), max(l, p["date"]))
    for a in arts:
        k = (a["store"], a["url"], a["name"]); f, l = fl.get(k, (a["first_seen"], a["last_seen"]))
        fl[k] = (min(x for x in [f, a["first_seen"]] if x), max(x for x in [l, a["last_seen"]] if x))
    db.executemany("INSERT OR REPLACE INTO seen VALUES(?,?,?,?,?)", [(*k, f, l) for k, (f, l) in fl.items()])
    db.commit(); log(f"database: restored {len(pts)} price points, {len(fl)} articles into {path}")
    return True

# ---------------------------------------------------------------------------------------- one-time Google Sheets import
def import_sheets(log=print):
    if meta_get("sheets_imported"): log("database: Google Sheets already imported"); return
    sa = os.environ.get("GOOGLE_SA_JSON")
    if not sa: log("database: GOOGLE_SA_JSON not set – Sheets import skipped"); return
    import gspread
    from gspread.http_client import BackOffHTTPClient
    gc = gspread.service_account_from_dict(json.loads(sa), http_client=BackOffHTTPClient)
    def flt(v):
        try: return float(str(v).replace(",", ".")) if str(v).strip() != "" else None
        except Exception: return None
    def num(v):
        f = flt(v); return None if f is None else int(round(f))
    def day(v):   # text date, or a Sheets date serial number
        f = flt(v)
        if f and 40000 < f < 60000: import datetime as _d; return (_d.date(1899, 12, 30) + _d.timedelta(days=int(f))).isoformat()
        return str(v)[:10]
    total = 0
    for book_id, book in [(_CFG.get("price_history_id"), "Price history"), (_CFG.get("daily_report_id"), "Daily report")]:
        if not book_id: continue
        sh = gc.open_by_key(book_id)
        for ws in sh.worksheets():
            vals = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
            if not vals: continue
            hdr = [str(h) or f"col{j+1}" for j, h in enumerate(vals[0])]
            rows = [dict(book=book, tab=ws.title, row_no=i, data={hdr[j] if j < len(hdr) else f"col{j+1}": v for j, v in enumerate(r) if v != ""})
                    for i, r in enumerate(vals[1:], start=2) if any(v != "" for v in r)]
            upsert("sheet_archive", rows, ["book", "tab", "row_no"], chunk=500); total += len(rows)
            log(f"database: archived {book} / {ws.title}: {len(rows)} rows")
            if book == "Price history" and ws.title == "Store promos":
                upsert("promos", [dict(date=day(r[0]), store=r[1], cat=r[2], name=r[3], price=num(r[4]), old=num(r[5]), claimed=flt(r[6]), low30=num(r[7]),
                                       real_cut=flt(r[8]), market_low=num(r[9]), verdict=r[10] if len(r) > 10 else None, source="sheets")
                                  for r in vals[1:] if len(r) > 4 and day(r[0])[:4].isdigit() and r[3]], ["date", "store", "name"])
            if book == "Price history" and ws.title == "Gigatron & WinWin":
                upsert("watch_terms", [dict(date=day(r[0]), store=r[1], term=r[2], name=r[3], price=num(r[4]), old=num(r[5]), low30=num(r[6]),
                                            url=r[10] if len(r) > 10 else None) for r in vals[1:] if len(r) > 4 and day(r[0])[:4].isdigit() and r[2]],
                       ["date", "store", "term"])
    meta_set("sheets_imported", time.strftime("%Y-%m-%d %H:%M")); log(f"database: Google Sheets import done ({total} rows archived)")

if __name__ == "__main__":
    if not enabled(): print("SUPABASE_SERVICE_KEY not set – nothing to do"); sys.exit(0)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "restore": sys.exit(0 if restore_history(Path(sys.argv[2] if len(sys.argv) > 2 else HERE / "history.sqlite")) else 1)
    elif cmd == "import-sheets": import_sheets()
    else: print(__doc__)
