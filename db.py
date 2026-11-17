"""
Online database (Supabase / Postgres, via its REST API) – replaces Google Sheets and keeps the price history permanently.

Secrets (GitHub → Settings → Secrets → Actions):  SUPABASE_SERVICE_KEY  (the project's secret / service_role key)
URL comes from config.json "supabase_url" (or env SUPABASE_URL).  Without a key everything here is skipped.

Tables: price_points (every price change, per URL), articles (one row per article: first/last seen, current price, specs),
promos (daily verified promos), watch (G1–G4 rows), watch_terms, drops, store_summary, runs, meta, sheet_archive.

    python db.py restore history.sqlite     # rebuild the local SQLite history from the database (cache was lost)
    python db.py import-sheets              # one-time copy of the old Google Sheets (needs GOOGLE_SA_JSON)
    python db.py report --force             # send the daily back-office e-mail now (needs BREVO_API_KEY)
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
def akey(store, url, name):
    """Short key of one listing – the same value the database computes: md5(store|url|name) as a uuid."""
    import hashlib, uuid
    return str(uuid.UUID(hashlib.md5(f"{store}|{url or ''}|{name}".encode("utf-8")).hexdigest()))

def push_history(sqlite_path, log=print):
    """Send every price point the database doesn't have yet (all of them the first time).
    Points refer to their listing by akey (the listing itself – store, url, name – lives once in `articles`)."""
    db = sqlite3.connect(str(sqlite_path))
    since = meta_get("points_through") or "0000-00-00"
    rows = [dict(akey=akey(s, u, n), date=d, price=p, old=o, low30=l) for s, u, n, d, p, o, l in
            db.execute("SELECT store,url,name,date,price,old,low30 FROM points WHERE date>=?", (since,))]
    if rows:
        upsert("price_points", rows, ["akey", "date"])
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
        sp = {a_: b_ for a_, b_ in (specs.get(k[1]) or {}).items() if not a_.startswith("_")}
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
    r, _ = _req("GET", f"promos?select=date&date=lt.{date}&source=eq.run&order=date.desc&limit=1")   # one row (paging 1 by 1 took 40 min)
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

# ---------------------------------------------------------------------------------------- daily back-office e-mail
BREVO_KEY = os.environ.get("BREVO_API_KEY", "")
TAB_NAMES = {"search": "Pretraga", "deals": "Akcije", "drops": "Pojeftinilo", "watch": "Pratim", "stores": "Prodavnice", "report": "Izveštaj", "fav": "Sačuvano", "admin": "Admin"}
FLAG_NAMES = {"disc": "samo na popustu", "real": "ispod 30-dnevnog minimuma", "xs": "jeftinije u drugoj radnji", "new": "cena promenjena danas"}
SORT_NAMES = {"save": "najveća ušteda", "claimed": "navedeni popust", "price": "cena", "verdict": "ocena", "since": "cena od", "low": "najniža u 30 dana", "xs": "druge radnje", "name": "naziv", "ppu": "cena po jedinici"}

def usage_report(day):
    """Website usage for `day` (Belgrade time) with month-to-date and year-to-date totals – one database call."""
    r, _ = _req("POST", "rpc/usage_report", {"day": day})
    return r

def report_html(u, runs=()):
    import html as _h
    e = lambda x: _h.escape(str(x if x is not None else ""))
    nf = lambda n: f"{int(n or 0):,}".replace(",", ".")
    def table(title, rows, heads, note=""):
        if not rows: return f'<h3 style="font:600 15px Arial;margin:22px 0 6px">{e(title)}</h3><p style="font:13px Arial;color:#6b7280;margin:0">–</p>'
        th = "".join(f'<th style="text-align:{"right" if i else "left"};padding:5px 8px;border-bottom:1px solid #d1d5db;font:600 12px Arial;color:#6b7280">{e(h)}</th>' for i, h in enumerate(heads))
        tr = "".join("<tr>" + "".join(f'<td style="text-align:{"right" if i else "left"};padding:5px 8px;border-bottom:1px solid #eef0f2;font:13px Arial">{e(c)}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
        return (f'<h3 style="font:600 15px Arial;margin:22px 0 6px">{e(title)}</h3>' + (f'<p style="font:12px Arial;color:#6b7280;margin:0 0 4px">{e(note)}</p>' if note else "") +
                f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;width:100%;max-width:640px"><tr>{th}</tr>{tr}</table>')
    def tile(label, value, sub=""):
        return (f'<td style="padding:12px 14px;background:#f3f6f4;border-radius:8px;width:25%;vertical-align:top"><div style="font:12px Arial;color:#6b7280">{e(label)}</div>'
                f'<div style="font:700 24px Arial;color:#14532d;margin-top:2px">{e(value)}</div><div style="font:12px Arial;color:#6b7280">{e(sub)}</div></td>')
    d, prev = u.get("users_day") or 0, u.get("users_prev") or 0
    delta = f"{'+' if d >= prev else '−'}{abs(round((d / prev - 1) * 100))}% prema danu ranije" if prev else ""
    c, au = u.get("counts") or {}, u.get("active_users") or {}
    share = lambda k: f"{round(100 * (au.get(k) or 0) / d)}%" if d else "–"
    beh = [["Koristili pretragu", nf(au.get("search")), share("search")], ["Koristili filtere", nf(au.get("filter")), share("filter")],
           ["Otvorili bar jedan artikal", nf(au.get("item")), share("item")], ["Kliknuli ka prodavnici", nf(au.get("out")), share("out")],
           ["Promenili karticu", nf(au.get("tab")), share("tab")], ["Sačuvali artikal", nf(au.get("fav")), share("fav")], ["Podelili link", nf(au.get("share")), share("share")],
           ["Otišli bez ijedne akcije", "", f"{nf(u.get('bounce_pct'))}%"], ["Na telefonu", "", f"{nf(u.get('mobile_pct'))}%"],
           ["Akcija po posetiocu (prosek)", "", str(u.get("events_per_user") or "–").replace(".", ",")]]
    peak = sorted(u.get("hours") or [], key=lambda x: -x[1])[:3]
    out = [f'<div style="max-width:660px;margin:0 auto;padding:8px 4px;color:#111827">',
           f'<h2 style="font:700 20px Arial;margin:0 0 2px">babl cene – dnevni izveštaj</h2><p style="font:13px Arial;color:#6b7280;margin:0 0 14px">Dan: {e(u.get("day"))} (juče) · korisnik = jedna poseta (sesija), bez kolačića</p>',
           '<table cellspacing="6" cellpadding="0" style="width:100%;max-width:640px"><tr>' + tile("Juče", nf(d), delta) + tile("Ovaj mesec (MTD)", nf(u.get("users_mtd"))) +
           tile("Ova godina (YTD)", nf(u.get("users_ytd"))) + tile("Klikova ka radnjama", nf(c.get("out")), "juče") + "</tr></table>",
           table("Ponašanje posetilaca (juče)", beh, ["", "Posetilaca", "Udeo"]),
           table("Najčešće pretrage – juče", [[q, n] for q, n in (u.get("searches_day") or [])[:15]], ["Pojam", "Posetilaca"]),
           table("Najčešće pretrage – ovaj mesec", [[q, n] for q, n in (u.get("searches_mtd") or [])[:15]], ["Pojam", "Posetilaca"]),
           table("Pretrage bez rezultata (juče)", [[q, n] for q, n in (u.get("no_results") or [])[:10]], ["Pojam", "Posetilaca"], "Šta ljudi traže, a sajt nema – ideje za nove kategorije ili radnje."),
           table("Najotvaraniji artikli (juče)", [[f"{i[:70]} · {s}", n] for i, s, n in (u.get("items") or [])[:10]], ["Artikal", "Posetilaca"]),
           table("Kartice", [[TAB_NAMES.get(t, t), n] for t, n in u.get("tabs") or []], ["Kartica", "Posetilaca"]),
           table("Klikovi ka prodavnicama", u.get("out") or [], ["Prodavnica", "Klikova"]),
           table("Odakle su došli", u.get("refs") or [], ["Izvor", "Poseta"]),
           table("Filteri: kategorije", (u.get("filter_cats") or [])[:8], ["Kategorija", "Posetilaca"]),
           table("Filteri: prodavnice", u.get("filter_stores") or [], ["Prodavnica", "Posetilaca"]),
           table("Filteri: prekidači i sortiranje", [[FLAG_NAMES.get(k, k), n] for k, n in u.get("filter_flags") or []] + [["sortiranje: " + SORT_NAMES.get(k, k), n] for k, n in u.get("sorts") or []], ["", "Posetilaca"]),
           table("Poslednjih 14 dana", [[x[0], nf(x[1])] for x in u.get("last14") or []], ["Dan", "Posetilaca"]),
           f'<p style="font:13px Arial;margin:16px 0 0">Najprometniji sati: {e(", ".join(f"{h}h ({n})" for h, n in peak) or "–")}</p>']
    if runs:
        out.append(table("Sistem – poslednja preuzimanja", [[f"{r['finished_at'][:16].replace('T', ' ')} UTC · {r['mode']}", f"{nf(r['articles'])} art." + (" · ⚠ " + r["problems"][:80] if r.get("problems") else " · OK")] for r in runs], ["Preuzimanje", "Rezultat"]))
    out.append('<p style="font:12px Arial;color:#9ca3af;margin:18px 0 0">Automatski izveštaj · cene.babl.cc · šalje se uz prvo jutarnje osvežavanje cena</p></div>')
    return "".join(out)

def _brevo(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("https://api.brevo.com/v3/" + path, data=data, method=method,
                                 headers={"api-key": BREVO_KEY, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read().decode("utf-8"); return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Brevo {path}: HTTP {e.code} {e.read().decode('utf-8', 'ignore')[:300]}")

def send_daily_report(today, hour, log=print, force=False):
    """Once a day, with the first run after 04:00 (the morning full run): e-mail yesterday's website usage (plus MTD / YTD) through Brevo.
    Recipient = REPORT_EMAIL, else the Brevo account's own sender address (so no address is kept in this public repository)."""
    if not (enabled() and BREVO_KEY): log("daily report: BREVO_API_KEY not set – skipped"); return False
    if not force and (hour < 4 or meta_get("report_sent") == today): return False
    import datetime as _d
    day = (_d.date.fromisoformat(today) - _d.timedelta(days=1)).isoformat()
    u = usage_report(day)
    runs, _ = _req("GET", "runs?select=finished_at,mode,articles,problems&order=id.desc&limit=6")
    senders = [s_ for s_ in _brevo("GET", "senders").get("senders", []) if s_.get("active")]
    if not senders: raise RuntimeError("Brevo has no active sender")
    to = os.environ.get("REPORT_EMAIL") or senders[0]["email"]
    _brevo("POST", "smtp/email", {"sender": {"name": "babl cene", "email": senders[0]["email"]}, "to": [{"email": to}],
                                  "subject": f"babl cene · {day}: {u.get('users_day') or 0} posetilaca (MTD {u.get('users_mtd') or 0}, YTD {u.get('users_ytd') or 0})",
                                  "htmlContent": "<html><body>" + report_html(u, runs) + "</body></html>"})
    meta_set("report_sent", today); log(f"daily report for {day} e-mailed")
    return True

# ---------------------------------------------------------------------------------------- restore
def restore_history(path, log=print):
    """Rebuild history.sqlite from the database (used when the GitHub cache expired)."""
    raw = select("price_points", "select=akey,date,price,old,low30&order=akey,date")
    if not raw: log("database: no price points to restore"); return False
    arts = select("articles", "select=akey,store,url,name,first_seen,last_seen")
    who = {a["akey"]: a for a in arts}
    pts = [dict(p, store=who[p["akey"]]["store"], url=who[p["akey"]]["url"], name=who[p["akey"]]["name"]) for p in raw if p["akey"] in who]
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
    elif cmd == "report":       # python db.py report [--force]  – send the daily e-mail now
        import datetime as _d; from zoneinfo import ZoneInfo
        n = _d.datetime.now(ZoneInfo("Europe/Belgrade")); send_daily_report(n.date().isoformat(), n.hour, force="--force" in sys.argv)
    else: print(__doc__)
