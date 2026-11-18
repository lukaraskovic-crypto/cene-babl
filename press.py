"""
"Data for journalists": today's aggregate numbers on advertised discounts (old price > today's price, price >= 3,000 din).

    compute(site_dir)       -> dict: overall, top 15 categories, per store (per-store is for the owner only)
    pages(site, W, log)     -> called from seo.build(): writes podaci.html (sr), en/podaci.html, podaci.csv, podaci.json
    owner_html(site_dir)    -> "Za medije" snippet for the owner's morning e-mail (press note + per-store table); never raises

    python press.py site    # print today's public numbers

Per-store numbers are never written to the (public) site directory; they only appear in owner_html().
Buckets follow the verdicts of bf_watch.own_verdict: REAL CUT (>= 5% below the 30-day low), PRICE RAISED (> 2% above it),
FAKE (not 5% below, advertised >= 10%), "No real change" (same, advertised < 10%), everything else = unverified (no 30-day low).
"""
import csv, io, json, statistics, sys, datetime as dt
from pathlib import Path

import seo

MIN_PRICE = 3000
TOP_CATS = 15
LANGS = ("sr", "en")
STORES = ["Gigatron", "WinWin", "Big Bang", "Ananas", "PC Practic", "Eurotehna", "Tehnomedia"]
KEYS = ("confirmed", "not_lower", "above_low", "near_low", "unverified")


def bucket(v):
    v = v or ""
    if v.startswith("REAL CUT"): return "confirmed"
    if v.startswith("FAKE"): return "not_lower"
    if v.startswith("PRICE RAISED"): return "above_low"
    if v.startswith("No real"): return "near_low"
    return "unverified"


def _r1(x): return None if x is None else round(x * 100, 1)


def _agg(items):
    n = len(items)
    o = {"advertised": n}
    for k in KEYS:
        c = sum(1 for a in items if a["b"] == k)
        o[k] = c; o["share_" + k] = round(c / n * 100, 1) if n else None
    real = [a["real"] for a in items if a["b"] == "confirmed" and a["real"] is not None]
    o["avg_advertised_pct"] = _r1(statistics.fmean(a["claimed"] for a in items)) if items else None
    o["avg_real_pct"] = _r1(statistics.fmean(real)) if real else None
    o["median_real_pct"] = _r1(statistics.median(real)) if real else None
    return o


def compute(site_dir):
    """Today's numbers from the built site (site/data.js + data-N.js, read exactly like seo.load)."""
    data, rows = seo.load(Path(site_dir))
    C = {c: i for i, c in enumerate(data["cols"])}
    tracked, items, names = 0, [], {}
    for r in rows:
        p = r[C["price"]]
        if not p: continue
        tracked += 1
        old, low = r[C["old"]] or 0, r[C["low30"]] or 0
        if p < MIN_PRICE or not old > p: continue
        cat = seo.cat_name(r[C["cat"]]); ck = seo.slug(cat, 60) if cat else ""
        if ck: names.setdefault(ck, {}); names[ck][cat] = names[ck].get(cat, 0) + 1
        b = bucket(r[C["verdict"]])
        items.append(dict(store=r[C["store"]], ck=ck, b=b, claimed=1 - p / old, real=(1 - p / low) if (b == "confirmed" and low) else None))
    bycat, bystore = {}, {}
    for a in items:
        if a["ck"]: bycat.setdefault(a["ck"], []).append(a)
        bystore.setdefault(a["store"], []).append(a)
    cname = lambda k: max(names[k], key=lambda c: (names[k][c], c != seo.fold(c)))
    top = sorted(bycat, key=lambda k: (-len(bycat[k]), cname(k)))[:TOP_CATS]
    return {
        "date": data["date"], "updated": data.get("updated", data["date"]), "min_price": MIN_PRICE, "threshold_pct": 5,
        "tracked": tracked, "stores_covered": STORES,
        "overall": _agg(items),
        "categories": [{"category": cname(k), "slug": k, **_agg(bycat[k])} for k in top],
        "stores": [{"store": s, **_agg(v)} for s, v in sorted(bystore.items(), key=lambda kv: -len(kv[1]))],   # owner only
    }


def public(res):
    """Everything that may be published (no per-store numbers)."""
    return {k: v for k, v in res.items() if k != "stores"} | {
        "source": f"babl cene (cene.babl.cc), podaci od {_date('sr', res)}",
        "methodology": seo.BASE + "/podaci.html",
        "definitions": {
            "advertised": f"items >= {MIN_PRICE} din whose crossed-out price is higher than today's price",
            "confirmed": "today's price at least 5% below the lowest price of the 30 days before the reduction",
            "not_lower": "not at least 5% below that price (and not more than 2% above), advertised discount >= 10%",
            "above_low": "today's price more than 2% above the 30-day low",
            "near_low": "not at least 5% below that price (and not more than 2% above), advertised discount < 10%",
            "unverified": "no 30-day low available",
            "share_*": "percent of advertised discounts",
            "avg_advertised_pct": "mean of 1 - price / crossed-out price",
            "avg_real_pct": "mean of 1 - price / 30-day low, confirmed reductions only",
            "median_real_pct": "median of 1 - price / 30-day low, confirmed reductions only",
            "tracked": "all products with a price in today's data (any price)",
        }}


def _date(l, res):
    S = seo.texts()[l]["seo"]
    return seo.dfmt(S, dt.date.fromisoformat(res["date"])).rstrip(".")


def _pc(x, l, dec=None):
    if x is None: return "–"
    if x == 0: return "0%"
    dec = dec or seo.texts()[l]["seo"]["press"]["dec"]
    s = f"{x:.1f}" if abs(x) < 10 else f"{round(x)}"
    return s.replace(".", dec) + "%"


def _csv(res):
    cols = [("kategorija", None), ("istaknutih_popusta", "advertised"),
            ("potvrdjeno_snizenje", "confirmed"), ("potvrdjeno_udeo_pct", "share_confirmed"),
            ("nije_nize_od_30_dana", "not_lower"), ("nije_nize_udeo_pct", "share_not_lower"),
            ("iznad_30_dnevnog_minimuma", "above_low"), ("iznad_minimuma_udeo_pct", "share_above_low"),
            ("blizu_30_dnevnog_minimuma", "near_low"), ("blizu_minimuma_udeo_pct", "share_near_low"),
            ("bez_provere", "unverified"), ("bez_provere_udeo_pct", "share_unverified"),
            ("prosecan_istaknuti_popust_pct", "avg_advertised_pct"), ("prosecno_stvarno_snizenje_pct", "avg_real_pct"),
            ("medijana_stvarnog_snizenja_pct", "median_real_pct")]
    f = io.StringIO(); w = csv.writer(f, lineterminator="\n")
    w.writerow(["datum"] + [c for c, _ in cols])
    for name, o in [("Sve kategorije", res["overall"])] + [(c["category"], c) for c in res["categories"]]:
        w.writerow([res["date"], name] + ["" if o[k] is None else o[k] for _, k in cols[1:]])
    return "﻿" + f.getvalue()     # BOM so Excel reads č/ć/š


def _body(l, res):
    S = seo.texts()[l]["seo"]; P = S["press"]; e, nf, F = seo.e, seo.nf, seo.F
    o = res["overall"]; d = _date(l, res)
    sh = lambda k: e(F(P["share"], p=_pc(o["share_" + k], l)))
    tiles = [(P["k_adv"], nf(o["advertised"]), ""), (P["k_real"], nf(o["confirmed"]), sh("confirmed")),
             (P["k_fake"], nf(o["not_lower"]), sh("not_lower")), (P["k_raised"], nf(o["above_low"]), sh("above_low")),
             (P["k_near"], nf(o["near_low"]), sh("near_low")), (P["k_unv"], nf(o["unverified"]), sh("unverified")),
             (P["k_avg_adv"], _pc(o["avg_advertised_pct"], l), ""), (P["k_avg_real"], _pc(o["avg_real_pct"], l), ""),
             (P["k_med_real"], _pc(o["median_real_pct"], l), ""), (P["k_tracked"], nf(res["tracked"]), "")]
    dl = "".join(f'<div><dt>{e(k)}</dt><dd>{v}{(f"<br><small style=font-weight:400>{s}</small>") if s else ""}</dd></div>' for k, v, s in tiles)
    pcs = lambda c, k: f'{nf(c[k])}<br><small>{_pc(c["share_" + k], l)}</small>'
    row = lambda name, c, b=False: (f'<tr{" style=font-weight:700" if b else ""}><td>{e(name)}</td><td>{nf(c["advertised"])}</td><td>{pcs(c, "confirmed")}</td>'
                                    f'<td>{pcs(c, "not_lower")}</td><td>{pcs(c, "above_low")}</td><td>{pcs(c, "unverified")}</td>'
                                    f'<td>{_pc(c["avg_advertised_pct"], l)}<br><small>{_pc(c["avg_real_pct"], l)}</small></td></tr>')
    th = "".join(f"<th>{e(P[k])}</th>" for k in ("th_cat", "th_adv", "th_real", "th_fake", "th_raised", "th_unv", "th_avg"))
    tbl = (f'<style>.pt{{font-size:12.5px}}.pt td,.pt th{{padding:6px 3px;vertical-align:top;hyphens:auto}}.pt th{{font-size:12px}}</style><div style="overflow-x:auto"><table class="pt"><thead><tr>{th}</tr></thead><tbody>'
           + row(P["total"], o, True) + "".join(row(c["category"], c) for c in res["categories"]) + "</tbody></table></div>")
    stores = ", ".join(res["stores_covered"])
    method = "".join(f"<p>{e(F(x, min=nf(MIN_PRICE), stores=stores))}</p>" for x in P["method"])
    cite = F(P["cite"], d=d)
    return (f"<h1>{e(P['h1'])}</h1><p>{e(F(P['intro'], min=nf(MIN_PRICE), n=len(res['stores_covered']), d=d, u=res['updated']))}</p>"
            f"<h2>{e(P['overall'])}</h2><div class='box'><dl style='grid-template-columns:repeat(auto-fit,minmax(140px,1fr))'>{dl}</dl></div>"
            f"<h2>{e(P['bycat'])}</h2>{tbl}<p class='bc'>{e(P['tbl_note'])}</p>"
            f"<h2>{e(P['method_h'])}</h2>{method}"
            f"<h2>{e(P['disc_h'])}</h2><div class='box'>{e(P['disc'])}</div>"
            f"<h2>{e(P['cite_h'])}</h2><div class='box'><b>{e(cite)}</b></div>"
            f"<h2>{e(P['dl_h'])}</h2><p><a class='btn pri' href='/podaci.csv' download>{e(P['dl_csv'])}</a><a class='btn' href='/podaci.json'>{e(P['dl_json'])}</a></p>"
            f"<p class='bc'>{e(P['dl_note'])}</p>")


def pages(site, W, log=print):
    """Hook for seo.build(): W(lang, path, html) writes a page and adds it to the sitemap."""
    site = Path(site); res = compute(site); TX = seo.texts()
    for l in LANGS:
        S = TX[l]["seo"]; P = S["press"]
        W(l, "podaci.html", seo.page(l, S, P["title"], P["desc"], "podaci.html", _body(l, res), [(P["crumb"], "")], alts=LANGS))
    (site / "podaci.csv").write_text(_csv(res), encoding="utf-8")
    (site / "podaci.json").write_text(json.dumps(public(res), ensure_ascii=False, indent=1), encoding="utf-8")
    o = res["overall"]
    log(f"press: {o['advertised']} advertised discounts, {o['confirmed']} confirmed, {len(res['categories'])} categories → podaci.html/csv/json")
    return res


def press_note(res):
    """4–6 sentence Serbian press note with today's overall numbers (neutral wording)."""
    o = res["overall"]; nf = seo.nf; d = _date("sr", res); p = lambda k: _pc(o["share_" + k], "sr")
    s = [f"Prema podacima sajta babl cene od {d}, koji prati cene {nf(res['tracked'])} proizvoda u {len(res['stores_covered'])} prodavnica tehnike "
         f"({', '.join(res['stores_covered'])}), istaknut popust ima {nf(o['advertised'])} artikala od {nf(MIN_PRICE)} din naviše.",
         f"Od {nf(o['advertised'])} istaknutih popusta, {nf(o['confirmed'])} ({p('confirmed')}) je bar 5% ispod najniže cene iz 30 dana pre sniženja, "
         f"a kod {nf(o['not_lower'])} ({p('not_lower')}) cena nije niža od te cene (ili je niža manje od 5%).",
         f"Kod još {nf(o['near_low'])} ({p('near_low')}) cena je blizu tog minimuma uz istaknuti popust manji od 10%, kod {nf(o['above_low'])} ({p('above_low')}) "
         f"današnja cena je iznad najniže cene iz 30 dana, a za {nf(o['unverified'])} ({p('unverified')}) ta cena nije bila dostupna."]
    if o["avg_real_pct"] is not None:
        s.append(f"Prosečan istaknuti popust iznosi {_pc(o['avg_advertised_pct'], 'sr')}, dok je stvarno sniženje kod potvrđenih u proseku "
                 f"{_pc(o['avg_real_pct'], 'sr')} (medijana {_pc(o['median_real_pct'], 'sr')}).")
    s.append("Poređene su samo javno objavljene cene, u skladu sa pravilom Zakona o trgovini da je prethodna cena najniža cena iz 30 dana pre sniženja; "
             "to nije pravna ocena niti tvrdnja o namerama prodavaca.")
    s.append(f"Metodologija, podaci po kategorijama i CSV: {seo.BASE}/podaci.html (izvor: babl cene, cene.babl.cc, podaci od {d}).")
    return " ".join(s)


def owner_html(site_dir):
    """"Za medije" block for the owner's morning e-mail. Per-store numbers live only here. Never raises."""
    esc = lambda x: str(x if x is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    h3 = '<h3 style="font:600 15px Arial;margin:22px 0 6px">Za medije</h3>'
    try:
        res = compute(site_dir)
        if not res["overall"]["advertised"]: return h3 + '<p style="color:#6b7280">Danas nema istaknutih popusta u podacima.</p>'
        pc = lambda x: _pc(x, "sr", ",")
        td = 'style="padding:3px 10px 3px 0;white-space:nowrap"'
        rows = "".join(f'<tr><td {td}>{esc(s["store"])}</td><td {td}>{seo.nf(s["advertised"])}</td><td {td}>{pc(s["share_confirmed"])}</td>'
                       f'<td {td}>{pc(s["share_not_lower"])}</td><td {td}>{pc(s["share_near_low"])}</td><td {td}>{pc(s["share_above_low"])}</td>'
                       f'<td {td}>{pc(s["share_unverified"])}</td><td {td}>{pc(s["avg_advertised_pct"])} / {pc(s["avg_real_pct"])}</td></tr>' for s in res["stores"])
        return (h3 + '<p style="color:#6b7280;margin:0 0 6px">Saopštenje spremno za slanje (brojevi od danas, sve prodavnice zajedno). '
                f'Javna strana: <a href="{seo.BASE}/podaci.html">{seo.BASE}/podaci.html</a> · <a href="{seo.BASE}/podaci.csv">CSV</a></p>'
                '<pre style="white-space:pre-wrap;background:#f3f6f4;border-radius:8px;padding:12px;font:13px/1.5 Arial">' + esc(press_note(res)) + "</pre>"
                '<p style="margin:14px 0 4px"><b>Po prodavnicama</b> <span style="color:#b3261e">– samo za vas – ne objavljivati po prodavnicama bez provere</span></p>'
                '<table style="border-collapse:collapse;font-size:12px"><tr style="color:#6b7280;text-align:left"><th>Prodavnica</th><th>Popusta</th><th>Potvrđeno</th>'
                '<th>Nije niže</th><th>Blizu min.</th><th>Iznad min.</th><th>Bez provere</th><th>Istaknuto / stvarno</th></tr>' + rows + "</table>"
                '<p style="color:#9ca3af;font-size:12px">Udeli od broja istaknutih popusta (≥ 3.000 din). '
                'Razlike među prodavnicama zavise i od toga koliko artikala ima prethodnu cenu koju možemo da proverimo.</p>')
    except Exception as ex:
        return h3 + f'<p style="color:#6b7280">Nije dostupno ({esc(ex)})</p>'


if __name__ == "__main__":
    print(json.dumps(public(compute(sys.argv[1] if len(sys.argv) > 1 else "site")), ensure_ascii=False, indent=1))
