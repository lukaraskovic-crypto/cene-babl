# Cene · babl — Serbian electronics price watch

Website: **https://cene.babl.cc** (Serbian by default, English toggle, works on phones).

GitHub Actions crawls Gigatron, WinWin, Big Bang, Ananas, PC Practic and Eurotehna (+ Emmezeta status), checks every discount against the
store's own legally required 30-day lowest price, compares promos with all sellers on pametno.rs, and publishes the site.

| When (Belgrade) | What |
|---|---|
| 04:00 | **full**: all stores in parallel + pametno.rs + Google Sheets + phone notification |
| 10:40 · 14:40 · 18:40 | **refresh**: all stores in parallel, website + price history only |

Speed-ups: one parallel job per store; each store's full crawl has a time limit (`full_store_minutes`, 60);
30-day lows read from product pages are cached and reused while the price is unchanged (`low30_cache_days`, 5);
pametno.rs runs as its own parallel job on yesterday's term list and its results are reused for `pametno_cache_days` (4).

Website tabs: search (filters, sort on every column, "price since" date and price-history chart per article),
deals & fake discounts, price drops, watch list (G1 Xiaomi G20 Max, G2 tablets with SIM, G3 tablets with ≥8 GB RAM + SIM and
good specs), stores, report. Owner-only tab: **https://cene.babl.cc/#admin → Kategorije**.

## Choosing categories for the detailed crawl
Open `#admin`, untick categories, press **Copy & open GitHub**, paste into `categories.json` and **Commit changes**.
Only the repository owner can commit, so only you can change it. Takes effect from the next run.

## Files
`bf_watch.py` (crawl, verdicts, Sheets, `--only <store>` / `--combine` / `--refresh`), `catalog.py` (full-catalogue crawlers,
price history), `pw_site.py` + `site_template.html` (website), `categories.json`, `config.json`, `.github/workflows/daily.yml`.

## One-time setup (done)
Pages source GitHub Actions; secret `GOOGLE_SA_JSON`; optional secret `NTFY_TOPIC`; variables `SITE_DOMAIN`, `SITE_URL`;
DNS CNAME `cene` → `lukaraskovic-crypto.github.io`.

Tehnomanija, DOTmarket and Bazzar show GitHub's servers a Cloudflare bot check, so they are skipped (crawlers kept in catalog.py; their prices still appear in the pametno.rs market comparison).
