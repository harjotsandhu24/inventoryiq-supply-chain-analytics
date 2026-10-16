# Data access, terms and reproduction

## Source

The **Walmart M5 Forecasting - Accuracy** dataset (University of Nicosia / MOFC, hosted on Kaggle): https://www.kaggle.com/competitions/m5-forecasting-accuracy/data

Files used: `calendar.csv`, `sales_train_evaluation.csv`, `sales_train_validation.csv`, `sell_prices.csv`.

## Terms and what this repository does about them

The competition's Rules page lists the data-access terms as **"Competition Use, Academic, Non-Commercial Use."** Read the full Rules and Data tabs yourself before using or sharing anything derived from the data. This repository follows a conservative policy:

| Content | In the public repository? |
|---|---|
| Raw M5 CSV files | **No.** `data/raw/` is git-ignored. |
| Row-level M5-derived outputs (app JSON, recommendation CSVs, the M5 Excel workbook, the DuckDB database) | **No.** Generated locally and git-ignored. |
| Detailed aggregate reports (`reports/m5/`, `docs/results.md`) | **No.** Generated locally only. |
| Numerical findings from the M5 analysis | **No.** Kept private; the README states qualitative conclusions only. |
| Application screenshots and demo video | Yes, captured on **synthetic** data only (M5 captures are kept in the git-ignored `private/`) |
| Synthetic demo data in M5 format (`SYN_` item ids, random draws) | Yes. The app runs on it out of the box. |

## Reproduce with the real data

1. Sign in to Kaggle and accept the competition rules. Then download the data with the Kaggle CLI (`kaggle competitions download -c m5-forecasting-accuracy`) or from the Data tab.
2. Extract the four CSV files into `data/raw/`.
3. Run the pipeline (about 15 minutes on a 12-core laptop with 32 GB RAM; the gradient-boosting fits are cached afterwards):

   ```powershell
   .\.venv\Scripts\python.exe -m inventoryiq.pipeline --source m5
   ```

4. Start the app. It loads `app/public/data`, which the pipeline has just written.

## Without the real data

```powershell
.\.venv\Scripts\python.exe -m inventoryiq.pipeline --source synthetic
```

This generates M5-format synthetic files in `data/synthetic/` and runs the same pipeline. The app uses the committed synthetic fixture automatically when no real data is present, and the header shows a "Synthetic demo data" badge.
