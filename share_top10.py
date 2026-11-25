"""
Daily share images of the Top 10 real reductions (no AI involved), rendered after every website build.

    python share_top10.py site

Reads site/top10.json (written by seo.py) and the date in site/data.js, and writes into site/share/:
  top10-story.png            1080x1920 (Instagram / Viber story; text kept out of the top 250 px and bottom 300 px)
  top10-story.jpg            same story as JPEG (the Instagram API only takes JPEG)
  stories/<id>.jpg           fixed highlight stories from social/stories.html (Top 10, Zakon, Jezici, Pristupačnost)
  top10-story-YYYY-MM-DD.png dated copy of the story
  top10-square.png           1080x1350 (feed / LinkedIn)
  caption.txt                ready-to-paste Serbian caption with the top 3 and the link
  posted.txt                 date of the last Telegram post (see below)
Published at https://cene.babl.cc/share/... with the rest of the site. Empty or missing top10.json: exits 0, no images.

Telegram (optional): with env TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID the story is sent once per data date (sendPhoto).
De-duplication: the live site's https://cene.babl.cc/share/posted.txt holds the last posted date. If it equals today's
data date, nothing is sent; otherwise the photo is sent and the new date is written to site/share/posted.txt, which the
deploy publishes. Every run copies the live value forward, so refresh runs keep the marker. If the live file cannot be
read (network error, not a 404), nothing is posted and today's date is written, so a hiccup never causes a double post
(at worst one day is skipped). The dated story copy is only kept for the current day (the site is rebuilt every run).
"""
import datetime as dt, html, json, os, re, shutil, sys, urllib.error, urllib.request, uuid
from pathlib import Path

SITE_URL = (os.environ.get("SITE_URL") or "https://cene.babl.cc").rstrip("/")
LINK = "https://cene.babl.cc/top10.html?utm_source=social&utm_campaign=top10"
MON = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "avg", "sep", "okt", "nov", "dec"]
FOOT = "Poređenje objavljenih cena. Proverite cenu kod prodavca."


def nf(n):  # 12345 -> 12.345
    return f"{round(n):,}".replace(",", ".")


def short(name, n=45):
    name = re.sub(r"\s+", " ", str(name)).strip()
    if len(name) <= n: return name
    cut = name[:n + 1].rsplit(" ", 1)[0] if " " in name[:n + 1] else name[:n]
    return cut.rstrip(" ,;-–/(") + "…"


def pct(a):
    return round((1 - a["price"] / a["low30"]) * 100) if a.get("low30") and a["low30"] > a["price"] else 0


def data_date(site):
    try:
        m = re.search(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})', (site / "data.js").read_text(encoding="utf-8")[:4000])
        if m: return dt.date.fromisoformat(m.group(1))
    except Exception:
        pass
    return dt.date.today()


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:%(W)dpx;height:%(H)dpx;background:#F6F7F3;color:#13201A;font-family:Manrope,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
.bar{position:absolute;left:0;top:0;width:100%%;height:14px;background:#1F6B45}
.safe{position:absolute;left:72px;right:72px;top:%(T)dpx;bottom:%(B)dpx;display:flex;flex-direction:column}
.wm{font-weight:800;font-size:%(wm)dpx;letter-spacing:-.02em;line-height:1}.wm b{color:#1F6B45}
h1{font-weight:800;font-size:%(h1)dpx;line-height:1.15;letter-spacing:-.02em;margin:%(h1m)dpx 0 %(gap)dpx}
h1 span{color:#1F6B45;white-space:nowrap}
.list{display:flex;flex-direction:column;gap:%(gap)dpx;flex:1;min-height:0}
.it{background:#fff;border-radius:28px;padding:%(pad)dpx 30px;display:flex;align-items:center;gap:26px;flex:1;min-height:0}
.n{flex:none;width:%(nw)dpx;height:%(nw)dpx;border-radius:50%%;background:#E3F3EA;color:#1F6B45;font-weight:800;font-size:%(nf)dpx;display:flex;align-items:center;justify-content:center}
.mid{flex:1;min-width:0}
.nm{font-weight:700;font-size:%(nm)dpx;line-height:1.15;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.st{color:#5B6B62;font-weight:700;font-size:%(st)dpx;line-height:1.1;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}
.pr{margin-top:6px;font-size:%(st)dpx;line-height:1.2;color:#5B6B62;font-weight:600;white-space:nowrap}
.pr b{color:#13201A;font-weight:800;font-size:%(pr)dpx;margin-right:14px}
.pr s{text-decoration-thickness:3px}
.pc{flex:none;background:#1F6B45;color:#fff;font-weight:800;font-size:%(pc)dpx;border-radius:999px;padding:12px 22px;white-space:nowrap}
.ft{margin-top:%(gap)dpx;font-size:%(ft)dpx;color:#5B6B62;font-weight:600;line-height:1.35}
.ft b{color:#1F6B45;font-weight:800}
"""


def page(items, day, W, H, top, bottom, sz):
    rows = "".join(
        f'<div class="it"><div class="n">{i}</div><div class="mid"><div class="st">{html.escape(a["store"])}</div>'
        f'<div class="nm">{html.escape(short(a["name"]))}</div>'
        f'<div class="pr"><b>{nf(a["price"])} din</b>umesto <s>{nf(a["low30"])}</s></div></div>'
        f'<div class="pc">−{pct(a)}%</div></div>' for i, a in enumerate(items, 1))
    css = CSS % dict(W=W, H=H, T=top, B=bottom, **sz)
    return (f'<!doctype html><html lang="sr"><head><meta charset="utf-8">'
            f'<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&display=block" rel="stylesheet">'
            f'<style>{css}</style></head><body><div class="bar"></div><div class="safe">'
            f'<div class="wm">babl <b>cene</b></div>'
            f'<h1>Top 10 stvarnih sniženja – <span>{day.day}. {MON[day.month - 1]}</span></h1>'
            f'<div class="list">{rows}</div>'
            f'<div class="ft"><b>cene.babl.cc</b> · {FOOT}</div></div></body></html>')


def render(out_png, doc, W, H):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            try: pg.set_content(doc, wait_until="networkidle", timeout=20000)
            except Exception: pg.set_content(doc, wait_until="load", timeout=20000)   # fonts unreachable: system font
            pg.evaluate("document.fonts.ready.then(()=>1)")
            over = pg.evaluate("""() => [...document.querySelectorAll('.safe,.list,.it,.mid,h1,.ft')].filter(e => e.scrollHeight > e.clientHeight + 2 || e.scrollWidth > e.clientWidth + 2).length""")
            if over: print(f"share_top10: warning, {over} element(s) overflow in {out_png.name}")
            kw = dict(type="jpeg", quality=88) if out_png.suffix == ".jpg" else {}
            pg.screenshot(path=str(out_png), clip={"x": 0, "y": 0, "width": W, "height": H}, **kw)
        finally:
            b.close()


def stories(share):
    """Fixed Instagram highlight stories from social/stories.html (one 1080x1920 div.s per story) -> share/stories/<id>.jpg.
    JPEG because the Instagram API only accepts JPEG; the files are public, so a posting tool can use their URLs."""
    src = Path(__file__).resolve().parent / "social" / "stories.html"
    if not src.exists(): return
    out = share / "stories"; out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1100, "height": 2000}, device_scale_factor=1)
                try: pg.set_content(src.read_text(encoding="utf-8"), wait_until="networkidle", timeout=30000)
                except Exception: pg.set_content(src.read_text(encoding="utf-8"), wait_until="load", timeout=20000)
                pg.evaluate("document.fonts.ready.then(()=>1)")
                ids = pg.evaluate("() => [...document.querySelectorAll('div.s[id]')].map(e => e.id)")
                for i in ids:
                    pg.locator("#" + i).screenshot(path=str(out / f"{i}.jpg"), type="jpeg", quality=88)
                print(f"share_top10: wrote {len(ids)} highlight stories to {out}")
            finally:
                b.close()
    except Exception as e:
        print(f"share_top10: stories failed: {type(e).__name__}: {e}")


def caption(top, day):
    lines = [f"🔥 Top 10 stvarnih sniženja – {day.day}. {MON[day.month - 1]}"]
    for i, a in enumerate(top[:3], 1):
        lines.append(f"{i}. {short(a['name'])} – {nf(a['price'])} din umesto {nf(a['low30'])} (−{pct(a)}%, {a['store']})")
    lines.append(f"Svih 10: {LINK} · {FOOT}")
    return "\n".join(lines) + "\n"


def live_posted():
    """Last posted date from the live site: '' when the file does not exist yet, None when it cannot be read."""
    try:
        with urllib.request.urlopen(f"{SITE_URL}/share/posted.txt?t={uuid.uuid4().hex[:8]}", timeout=15) as r:
            return r.read().decode("utf-8", "replace").strip()[:10]
    except urllib.error.HTTPError as e:
        return "" if e.code == 404 else None
    except Exception:
        return None


def telegram(share, png, cap, day):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat: return   # secrets not set: skip silently
    last = live_posted()
    if last: (share / "posted.txt").write_text(last + "\n", encoding="utf-8")   # carry the marker forward
    if last is None:   # unknown: skip, and mark today so the next run cannot double-post after a lost marker
        (share / "posted.txt").write_text(day.isoformat() + "\n", encoding="utf-8")
        print("share_top10: live posted.txt unreadable – not posting to Telegram this run"); return
    if last == day.isoformat(): print("share_top10: already posted to Telegram today"); return
    if png is None: return   # images failed: nothing to post (marker already carried forward)
    b = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", chat), ("caption", cap[:1024])):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="top10.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
                 + png.read_bytes() + b"\r\n")
    body = b"".join(parts) + f"--{b}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendPhoto", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            ok = json.loads(r.read()).get("ok")
    except urllib.error.HTTPError as e:   # never print the URL (it contains the token)
        print(f"share_top10: Telegram refused the post (HTTP {e.code}): {e.read()[:300].decode('utf-8', 'replace')}"); return
    except Exception as e:
        print(f"share_top10: Telegram post failed ({type(e).__name__})"); return
    if ok:
        (share / "posted.txt").write_text(day.isoformat() + "\n", encoding="utf-8")
        print("share_top10: posted to Telegram")


def main():
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
    stories(site / "share")
    try: top = json.loads((site / "top10.json").read_text(encoding="utf-8"))
    except Exception: top = []
    top = [a for a in top if a.get("price") and a.get("low30") and a["low30"] > a["price"]]
    if not top:
        print("share_top10: no top10.json data – no images"); return
    day = data_date(site)
    share = site / "share"; share.mkdir(parents=True, exist_ok=True)
    story = share / "top10-story.png"
    cap = caption(top, day)
    (share / "caption.txt").write_text(cap, encoding="utf-8")
    try:
        render(story, page(top[:5], day, 1080, 1920, 250, 300,
                           dict(wm=56, h1=58, h1m=28, gap=22, pad=18, nw=68, nf=34, nm=36, st=24, pr=42, pc=40, ft=24)), 1080, 1920)
        shutil.copy(story, share / f"top10-story-{day.isoformat()}.png")
        render(share / "top10-story.jpg", page(top[:5], day, 1080, 1920, 250, 300,
                                               dict(wm=56, h1=58, h1m=28, gap=22, pad=18, nw=68, nf=34, nm=36, st=24, pr=42, pc=40, ft=24)), 1080, 1920)
        render(share / "top10-square.png", page(top[:5], day, 1080, 1350, 64, 56,
                                                dict(wm=46, h1=58, h1m=22, gap=16, pad=16, nw=60, nf=30, nm=33, st=23, pr=38, pc=36, ft=25)), 1080, 1350)
        render(share / "top10-square.jpg", page(top[:5], day, 1080, 1350, 64, 56,      # feed post as JPEG (Instagram API)
                                                dict(wm=46, h1=58, h1m=22, gap=16, pad=16, nw=60, nf=30, nm=33, st=23, pr=38, pc=36, ft=25)), 1080, 1350)
        print(f"share_top10: wrote {share}/top10-story.png, top10-square.png, caption.txt ({day})")
    except Exception as e:
        print(f"share_top10: rendering failed: {type(e).__name__}: {e}")
        story = None
    telegram(share, story, cap, day)
    if story is None: sys.exit(1)


if __name__ == "__main__":
    main()
