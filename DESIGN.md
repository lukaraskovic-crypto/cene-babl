# babl cene – design direction

Written before restyling, so the site reads as made by a person for this product, not a template.

## Brand
- Colours and font come from the babl app (`babl/app/src/theme/tokens.ts`): deep green `#1F6B45`, mint `#CDEBD9`,
  warm neutral background `#F6F7F3`, text `#13201A`, muted `#5B6B62`, danger `#B3261E`; dark mode uses the app's dark palette.
- Font: **Manrope** (the app's font), not the default Inter. Brand is always lowercase: **babl cene**.
- Store marks: one small colour square per store, so the eye finds the store without reading.

## What we avoid (common "AI-made" tells)
Indigo/purple gradients, Inter everywhere, glass blur, identical rounded cards nested in cards, KPI-tile rows,
tracked all-caps labels, "A · B · C" meta strings, arrows on every link, motion on everything, invented numbers.

## Layout
- Open with the thing that matters: one plain sentence with today's numbers (how many products, how many real vs fake discounts).
- Tabular content is a real table (desktop) or a simple list (phone), on one surface; no card-in-card.
- Price is the strongest text on every row; crossed-out price below it; saving shown in dinars, not only %.
- Verdicts in plain words ("Pravi popust", "Lažni popust") and, in the detail view, one sentence explaining why.
- Price history is a step line (a price holds until it changes).

## Filtering (Baymard research)
- Few filter types → horizontal toolbar above results on desktop.
- Applied filters shown as removable chips with "Obriši sve".
- Phone: sticky bottom bar "Filteri | Sortiraj"; filters open full-screen with a "Prikaži N" button.

## Copy
Serbian (latinica) first, English toggle. Short, specific labels; dates as "12. nov"; amounts as "89.999 din".
The footer says how discounts are judged and that the site is not affiliated with any store.
