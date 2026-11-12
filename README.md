# Cene · babl — Serbian electronics price watch

Every morning (06:40 Belgrade) GitHub Actions crawls Gigatron, WinWin, Big Bang and Ananas (+ Emmezeta status),
checks every discount against the store's own legally required 30-day lowest price, compares promos with all sellers
on pametno.rs, updates the Google Sheets and publishes the website.

Website tabs: search all articles (filters + sort on every column, price-history chart per article),
real deals & fake discounts, price drops, watch items, stores, today's report.

Files: `bf_watch.py` (crawl + verdicts + sheets), `catalog.py` (full-catalogue crawlers + price history),
`pw_site.py` (website), `config.json` (settings), `.github/workflows/daily.yml` (schedule).

## One-time setup
1. Repo → Settings → Pages → Source: **GitHub Actions**.
2. Repo → Settings → Secrets and variables → Actions:
   - Secret `GOOGLE_SA_JSON` = the whole content of your `service_account.json`
   - (optional) Secret `NTFY_TOPIC` = your ntfy topic for phone pushes
   - Variable `SITE_DOMAIN` = `cene.babl.cc` and Variable `SITE_URL` = `https://cene.babl.cc`
3. At the DNS provider of babl.cc add a **CNAME** record: `cene` → `lukaraskovic-crypto.github.io`
4. Actions → "Daily price check" → **Run workflow** (tick "Skip pametno" for a quick first test).

Notes: Tehnomanija blocks automated browsers and is skipped (WinWin has the same catalogue).
pametno.rs allows ~16 requests/minute; `pametno_max_terms` (400) keeps the run within GitHub's 6-hour limit.
