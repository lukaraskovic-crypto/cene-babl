# Cene · babl — Serbian electronics price watch

Website: **https://cene.babl.cc** (Serbian by default, English toggle, works on phones).

GitHub Actions crawls Gigatron, WinWin, Big Bang, Ananas, PC Practic and Eurotehna (+ Emmezeta status), checks every discount against the
store's own legally required 30-day lowest price, compares promos with all sellers on pametno.rs, stores everything in an online
database (Supabase) and publishes the site.

| When (Belgrade) | What |
|---|---|
| 04:00 | **full**: every store's whole catalogue in parallel + pametno.rs + database + phone notification |
| 10:40 · 14:40 · 18:40 | **light refresh**: first 2 pages of every category, laid over the morning catalogue (≈10–15 min) |

Speed-ups: one parallel job per store; each store's full crawl has a time limit (`full_store_minutes`, 60);
product pages (30-day lows) are read only for articles ≥ `low30_min_price` whose price changed – otherwise the cached value is reused;
pametno.rs is looked up again only for new terms, failed lookups, a >3% change of our price, or after `pametno_recheck_days` (7).
Specifications are read from product pages once per article (new articles only, `spec_budget` per store per day) and kept.
Duplicate listings (same store, same name, same seller) are shown as one row – the cheapest – with "N oglasa".

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

## Files
`bf_watch.py` (crawl, verdicts, health check, `--only <store>` / `--light` / `--combine` / `--refresh`), `catalog.py` (full-catalogue
crawlers, spec reader, price history), `specs_js.js` (product-page specifications), `db.py` (database), `pw_site.py` +
`site_template.html` (website), `site_check.py`, `categories.json`, `config.json`, `.github/workflows/daily.yml`.

## One-time setup (done)
Pages source GitHub Actions; secret `SUPABASE_SERVICE_KEY`; optional secret `NTFY_TOPIC`
(`GOOGLE_SA_JSON` is only used for the one-time import of the old Sheets and can be deleted afterwards); variables `SITE_DOMAIN`, `SITE_URL`;
DNS CNAME `cene` → `lukaraskovic-crypto.github.io`.

Tehnomanija, DOTmarket and Bazzar show GitHub's servers a Cloudflare bot check, so they are skipped (crawlers kept in catalog.py; their prices still appear in the pametno.rs market comparison).
