# Data cleaning rules and exceptions

Principle: **never silently replace an invalid value with a plausible-looking number.** Each rule below says what is detected, how it is handled, and where it is enforced.

| # | Condition | Handling | Enforced in |
|---|---|---|---|
| 1 | Missing file, nulls in sales, duplicate series id, negative or non-integer quantity, duplicate price key, non-positive price, price week absent from the calendar | **Blocking error.** The pipeline stops. A loader also refuses sales files containing nulls rather than casting them. | `validate.py`, `data_io.py` |
| 2 | Day columns not contiguous `d_1..d_N` or calendar mismatch | Blocking error | `data_io.py`, `validate.py` |
| 3 | Validation file differs from the first 1,913 days of the evaluation file | Blocking error (inconsistent sources) | `validate.py` |
| 4 | Sales recorded on a day without a listed price (join or key problem) | Blocking error | `validate.py`, SQL check |
| 5 | Price join duplicates rows | Blocking error. Row count must equal series x days. | `validate.py`, SQL check |
| 6 | Item not yet introduced (no listed price) | Days are **unavailable**: excluded from averages, training rows and evaluation. Never treated as zero demand. | `data_io.Dataset.available`, all forecasters |
| 7 | Short history (< 365 listed days before holdout) | Kept in the full pipeline, excluded from the demo sample, and evaluated only if 56+ listed days precede a window | `sampling.py`, `backtest.evaluable` |
| 8 | Inactive item (no sales in the last 90 or 364 days) | Flagged. Excluded from the demo sample when the 364 pre-holdout days have zero sales. Zero-demand forecasts never trigger orders. | `sampling.py`, `policy.plan` |
| 9 | Long zero runs while listed (>= 90 days) | Flagged as possible stockouts or censored demand and **kept as observed**. Documented as a limitation. | `validate.py` |
| 10 | Demand spikes (>= 10x series mean and >= 20 units) | Flagged and kept. Spikes are real recorded sales. | `validate.py` |
| 11 | Price outliers (> 5x or < 0.2x item-store median) and prices < $0.10 | Flagged and kept. Unit cost uses the 364-day median price, which is robust to these. | `validate.py`, `suppliers.py` |
| 12 | Forecast denominators equal to zero (WAPE, MASE) | Reported as undefined (`null` / "n/a"), never as infinity or 0 | `metrics.py` |
| 13 | NaN or infinity in exported JSON | Converted to `null`. `allow_nan=False` makes any slip a hard error. | `util.write_json` |
| 14 | Negative forecasts | Clipped to 0 (count data) | `backtest.py`, `gbm.predict` |
| 15 | Invalid planning inputs (service level outside 50-99.9%, negative or NaN budget, review interval outside 1-28) | Rejected with a readable message in both engines. The UI shows it inline. | `policy.Settings.validate`, `engine.validateSettings` |
