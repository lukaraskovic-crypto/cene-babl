"""
Pre-publish check: the website is only deployed when its files are complete and plausible,
so a broken run can never replace a good site with an empty or half-built one.

    python site_check.py site
"""
import json, re, sys
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
MIN_ROWS = 80000   # the full site lists >100,000 articles; far fewer means something went wrong
err = []
idx = d / "index.html"
if not idx.exists(): err.append("index.html missing")
else:
    html = idx.read_text(encoding="utf-8")
    if "<!--DATA-->" in html or 'src="data.js"' not in html: err.append("index.html has no data scripts")
    if len(html) < 20000: err.append(f"index.html too small ({len(html)} bytes)")
rows = 0
try:
    t = (d / "data.js").read_text(encoding="utf-8")
    m = re.match(r"window\.DATA=(\{.*\});window\.DATA\.rows=\[\];$", t.strip(), re.S)
    data = json.loads(m.group(1)) if m else None
    if not data: err.append("data.js unreadable")
    elif not data.get("cols") or not data.get("updated"): err.append("data.js lacks cols/updated")
    for f in sorted(d.glob("data-*.js")):
        s = f.read_text(encoding="utf-8").strip()
        m2 = re.match(r"window\.DATA\.rows\.push\(\.\.\.(\[.*\])\);$", s, re.S)
        if not m2: err.append(f"{f.name} unreadable"); continue
        part = json.loads(m2.group(1)); rows += len(part)
        if part and data and len(part[0]) != len(data["cols"]): err.append(f"{f.name}: {len(part[0])} columns, expected {len(data['cols'])}")
except FileNotFoundError as e:
    err.append(f"missing {Path(e.filename).name}")
except Exception as e:
    err.append(f"data check failed: {e}")
if rows < MIN_ROWS: err.append(f"only {rows} articles (expected at least {MIN_ROWS})")
if not (d / "cats.js").exists(): err.append("cats.js missing")
if err:
    print("WEBSITE NOT PUBLISHED – " + "; ".join(err)); sys.exit(1)
print(f"website OK: {rows:,} articles")
