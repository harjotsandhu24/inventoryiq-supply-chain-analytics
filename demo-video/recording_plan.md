# InventoryIQ demonstration video

## Completed video (exists and is verified)

| Item | Value |
|---|---|
| File | `demo-video/inventoryiq_demo_synthetic.webm` (git-ignored; host it separately, see below) |
| Length | 52.2 seconds, 1440 x 900, VP8 WebM, about 5 MB |
| Data | **Synthetic demonstration data.** No Walmart M5 records appear in any frame. Provenance and hash: `inventoryiq_demo_synthetic.webm.manifest.json`. |
| Audio | None. It is silent, with on-screen captions. |
| How it was made | `app/scripts/record-demo.mjs` drives the real running app with Playwright and records the browser |
| Thumbnail | `demo-video/thumbnail.png`, a genuine capture of the Replenishment Planner on synthetic data |

Sequence:

1. Overview.
2. Identify the highest-risk product.
3. Open it in the Replenishment Planner (product selected).
4. Recommendation.
5. Step-by-step calculation.
6. Change service level to 99.5%.
7. Change lead time by +5 days, and watch the recalculation.
8. Scenario Lab.
9. Protect Availability.
10. Limit Spending.
11. Historical backtest.

The earlier silent video recorded on M5 data showed M5 product ids. It was moved to the git-ignored `private/m5-demo-video/` and must not be published.

To re-record, start the app on synthetic data (`cd app; npm.cmd run data:demo; npm.cmd run build; npm.cmd run start`), then in a second terminal run `node scripts/record-demo.mjs http://localhost:3000`.

## Optional narrated version (not recorded yet: this is a plan)

No narrated video exists. To add a voice-over, record the screen yourself while following the silent video's sequence, or narrate over the silent file in Clipchamp (Windows) or iMovie (macOS).

**Setup:** synthetic data running (header badge "Synthetic demo data"), browser at 1440 x 900 and 100% zoom, notifications off, purchase list cleared.

| # | Time | On screen | Say (read the numbers from the screen) |
|---|---|---|---|
| 1 | 0:00-0:08 | Overview | "InventoryIQ turns sales history into purchasing decisions. This is synthetic demonstration data." |
| 2 | 0:08-0:16 | Lines-at-risk KPI, top row of the table | "These products are likely to run out before a new order could arrive. This one is at the top." |
| 3 | 0:16-0:24 | Click the row: planner and recommendation | "The planner recommends how many units to order, what it costs, and when it arrives." |
| 4 | 0:24-0:34 | Calculation table | "Safety stock covers forecast error and supplier lead-time variability. Below the reorder point, it orders up to the target in whole cases." |
| 5 | 0:34-0:42 | What-if sliders | "If I ask for higher availability, or the supplier slows down, the recommendation recalculates immediately." |
| 6 | 0:42-0:55 | Scenario Lab: Protect Availability, then Limit Spending | "Across all products, higher availability costs more inventory, and a budget cut defers lower-priority orders, so expected shortages rise." |
| 7 | 0:55-1:05 | Historical backtest | "I also replayed history. In my Walmart analysis, a forecast-based policy needed order sizes that fit supplier capacity, and its cost advantage depended on order-processing costs." |

Only say numbers that are on screen. Say "synthetic" for the demo data and "simulated" for costs.

## Publishing the video (only after you approve)

1. Upload the WebM (or the narrated version) yourself to YouTube (Unlisted is fine), Loom or Google Drive. YouTube accepts WebM directly.
2. **README:** replace `Demo video: *link will be added once the video is hosted*` with `[Demo video](<your URL>)`.
3. **Notion:** replace `{{VIDEO_URL}}` in `notion-portfolio-package/02_inventoryiq_case_study.md`, or embed it with `/video`.
4. Do not commit video files to the repository (`*.webm` and `*.mp4` are git-ignored); link to the hosted copy instead.
