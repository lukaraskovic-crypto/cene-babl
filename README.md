# Cene · babl — Serbian electronics price watch

Website: **https://cene.babl.cc** (Serbian by default, English toggle, works on phones).

GitHub Actions crawls Gigatron, WinWin, Big Bang, Ananas, PC Practic, Eurotehna and Tehnomedia (+ Emmezeta status), checks every discount against the
store's own legally required 30-day lowest price, compares promos with all sellers on pametno.rs, stores everything in an online
database (Supabase) and publishes the site.

Runs are started on time by the database (Supabase cron jobs `cene-full`, `cene-refresh` → GitHub API; token in Vault `github_dispatch_token`, valid 1 year).

| When (Belgrade) | What |
|---|---|
| 04:00 | **full**: every store's whole catalogue in parallel + pametno.rs + database + phone notification |
| 10:40 · 14:40 · 18:40 | **light refresh**: first 2 pages of every category, laid over the morning catalogue (≈10–15 min) |

Speed-ups: one parallel job per store; each store's full crawl has a time limit (`full_store_minutes`, 60);
product pages (30-day lows) are read only for articles ≥ `low30_min_price` whose price changed – otherwise the cached value is reused;
pametno.rs is looked up again only for new terms, failed lookups, a >3% change of our price, or after `pametno_recheck_days` (7).
Specifications are read from product pages once per article (new articles only, `spec_budget` per store per day) and kept.
Duplicate listings are shown as one row – the cheapest offer – with "N ponuda": the same product from several sellers (Ananas),
the same name listed twice, and colours of one model at the same price. Verdicts belong to the exact listing (URL).

Health check: a store with 0 articles, a drop of more than 40% (`health_max_drop`), a crashed job or a database error
marks the run as failed (GitHub e-mails you), shows "⚠ problem" on the website and goes into the report.
The website is only published after `site_check.py` confirms it is complete.

Database: Supabase project `hxtdrtsqigvuvhaszxna` (tables price_points, articles, promos, watch, watch_terms, drops,
store_summary, runs, sheet_archive). Needs the GitHub secret `SUPABASE_SERVICE_KEY`. If the GitHub cache with
history.sqlite expires, it is rebuilt from the database. Google Sheets are no longer written; their old contents are
copied into the database once (table sheet_archive, plus promos / watch_terms).

Website tabs: search (filters, sort on every column, "price since" date and price-history chart per article),
deals & fake discounts, price drops, watch list (G1 Xiaomi G20 Max, G2 tablets with SIM, G3 tablets with ≥8 GB RAM + SIM and
good specs), stores, report. Owner-only tab: **https://cene.babl.cc/#admin → Kategorije**.

## Choosing categories for the detailed crawl
Open `#admin`, untick categories, press **Copy & open GitHub**, paste into `categories.json` and **Commit changes**.
Only the repository owner can commit, so only you can change it. Takes effect from the next run.

## Daily back-office e-mail
With the first run after 05:00 each day the combine job e-mails yesterday's website usage: visitors yesterday / month-to-date /
year-to-date, top searches, searches without results, most opened articles, tabs, clicks to shops, sources, filters used.
It is sent through Brevo (secret `BREVO_API_KEY`) to the Brevo account's own sender address, or to the secret `REPORT_EMAIL`.
The numbers come from the database function `usage_report(day)`. Send one by hand: `python db.py report --force`.

## babl account, saved articles and the store map
Visitors can sign in with their babl account (same login as babl.cc: Google or an e-mail link; Supabase project "babl").
Saved articles (★) are then kept in the account (table `cene_saved`, each user sees only their own rows) and synced between devices.
Signed-in users get "📍 Gde je na stanju" on Gigatron and WinWin articles and a map of all saved articles: the edge function
`cene-stock` (babl project, source in `supabase/functions/cene-stock`) asks the shop which stores have the article
(Gigatron's per-store API; WinWin's store list on the product page) and returns them with coordinates
(WinWin store locations: table `cene_store_geo`). The map (Leaflet + OpenStreetMap) sorts stores by distance from the visitor
or limits them to a city / the visible area. Tehnomedia refuses requests from the server, so it is not offered.

## Price-drop e-mails
Signed-in users can tick "🔔 Obavesti me emailom kad cena padne" in the Saved tab (table `cene_prefs`, opt-in, off by default).
After every run (full and refresh) `db.send_price_alerts` asks the babl edge function `cene-alerts` (source in
`supabase/functions/cene-alerts`; it accepts only this project's service key) for subscribers and their saved articles, and sends
one Brevo e-mail per user when an article is at least 3% and 200 din cheaper than when it was saved (or than at the last alert).
The alerted price is stored (`cene_saved.alert_price`) so the same drop is never mailed twice.

## Share images and search-engine pages
"🖼 Slika za Instagram / Viber" in an article draws a 1080×1920 image in the browser (price, verdict, chart, 30-day low) and opens
the phone's share sheet (or downloads it on a computer). `seo.py` writes plain-HTML pages after every build, also in "site" mode:
up to 5,000 article pages (`p/`), category and store pages, `popusti.html`, `crni-petak.html`, `sitemap.xml`, `robots.txt`.
Submit `https://cene.babl.cc/sitemap.xml` once in Google Search Console.

## Wording of the verdicts
Verdicts only compare published prices (today's price vs the lowest price the store states for the previous 30 days, which shops
must show since the 2026 amendments of the Zakon o trgovini). They are worded as facts ("Nije niže od 30 dana", "Iznad 30-dnevnog
minimuma"), never as accusations, and the footer says they are not a claim about a store's intentions nor a legal assessment.

## Files
`bf_watch.py` (crawl, verdicts, health check, `--only <store>` / `--light` / `--combine` / `--refresh`), `catalog.py` (full-catalogue
crawlers, spec reader, price history), `specs_js.js` (product-page specifications), `db.py` (database, daily e-mail, price alerts), `seo.py` (search-engine pages), `pw_site.py` +
`site_template.html` (website), `site_check.py`, `categories.json`, `config.json`, `.github/workflows/daily.yml`.

## One-time setup (done)
Pages source GitHub Actions; secret `SUPABASE_SERVICE_KEY`; optional secret `NTFY_TOPIC`
(`GOOGLE_SA_JSON` is only used for the one-time import of the old Sheets and can be deleted afterwards); variables `SITE_DOMAIN`, `SITE_URL`;
DNS CNAME `cene` → `lukaraskovic-crypto.github.io`.

Tehnomanija, DOTmarket and Bazzar show GitHub's servers a Cloudflare bot check, so they are skipped (crawlers kept in catalog.py; their prices still appear in the pametno.rs market comparison).
