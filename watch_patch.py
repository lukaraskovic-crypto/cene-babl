"""Website-only mode: rebuild the G3/G4 watch lists from the article data already on the live site (no crawl).
    python watch_patch.py site/      (expects data.js + data-N.js there; rewrites data.js)"""
import json, re, sys
from pathlib import Path
import bf_watch as b

site = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
head = (site / "data.js").read_text(encoding="utf-8")
data = json.loads(head[len("window.DATA="):head.rindex(";window.DATA.rows=[];")])
rows = []
for f in sorted(site.glob("data-*.js"), key=lambda p: int(p.stem.split("-")[1])):
    t = f.read_text(encoding="utf-8"); rows += json.loads(t[len("window.DATA.rows.push(..."):t.rindex(");")])
C = {c: i for i, c in enumerate(data["cols"])}
items = [dict(store=r[C["store"]], cat=r[C["cat"]], name=r[C["name"]], p=r[C["price"]], o=r[C["old"]] or None, l=r[C["low30"]] or None, u=r[C["url"]]) for r in rows]
W = [w for w in b.build_watch_candidates({}, items) if w["group"] in ("G3", "G4")]
date = data.get("date", b.TODAY)
out = []
for g, label, fn in [("G3", "G3 Tablet ≥8 GB RAM + SIM", b.tablet_info), ("G4", "G4 Laptop ≥32 GB RAM + ≥12 GB GPU", b.laptop_g4)]:
    ws = [w for w in W if w["group"] == g]
    def score(w):
        real = (1 - w["p"] / w["l"]) if w.get("l") else 0
        i = fn(w["name"]); return (0 if real >= .05 else 1, -(i["score"] / (w["p"] / 10000)) if i else 0)
    ws.sort(key=score); shown = set()
    for w in ws:
        if len([x for x in out if x[0] == label]) >= 30: break
        base = re.sub(r"\(.*?\)|\s[-–]\s[^-–]*$|\b(Gray|Grey|Graphite|Sivi|Siva|Crni|Starlight|Midnight|Blue|Purple|Space\s*Gr[ae]y|Moonstone|Silver|Black|White|Pink|Green|Mint|Navy)\b", "", w["name"], flags=re.I)
        k = (w["store"].split(" (")[0], re.sub(r"\W+", "", base.upper()))
        if k in shown: continue
        shown.add(k)
        wreal = round(1 - w["p"] / w["l"], 4) if w.get("l") else ""
        out.append([label, w["store"], w["name"], (fn(w["name"]) or {}).get("label", ""), w["p"], w.get("o") or "", w.get("l") or "", wreal, "", "", "", "", w.get("u", ""), date])
keep = [w for w in data.get("watch", []) if not str(w[0]).startswith(("G3", "G4"))]
data["watch"] = keep + out
(site / "data.js").write_text("window.DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";window.DATA.rows=[];", encoding="utf-8")
print(f"watch lists rebuilt from {len(rows)} articles:", {g: sum(1 for x in out if x[0].startswith(g)) for g in ("G3", "G4")})
