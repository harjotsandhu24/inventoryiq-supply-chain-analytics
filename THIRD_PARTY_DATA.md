# Third-party data notice

The MIT License in `LICENSE` (copyright (c) 2026 Harjot Sandhu) covers **only the original source code, documentation and synthetic demonstration data created for this project**. It grants no rights in any third-party data.

## Walmart M5 Forecasting - Accuracy dataset

- **Source:** https://www.kaggle.com/competitions/m5-forecasting-accuracy (competition hosted on Kaggle; data provided by Walmart)
- **Terms:** the competition's rules page lists data access as "Competition Use, Academic, Non-Commercial Use". Those terms, not the MIT License, govern the dataset and anything derived from it. Anyone reproducing the analysis must obtain the data from Kaggle and accept those terms themselves.
- **Not in this repository:**
  - the raw CSV files;
  - row-level derived files: application data, recommendation CSVs, the M5-based Excel workbook and the DuckDB database;
  - the detailed aggregate reports (`reports/m5/`, `docs/results.md`);
  - screenshots and video of the application running on M5 data.

  All of these are git-ignored and stay local.
- **Numerical results kept private:** forecast accuracy, simulation outcomes, costs and data counts from the author's analysis stay private (`private/`, `reports/m5/`, `docs/results.md`).
- **In this repository:** descriptions of the dataset's published structure (for example the number of series and the date range) and qualitative conclusions from the author's own non-commercial analysis, without figures. This is not a claim of permission to redistribute the dataset or results derived from it.

## Synthetic demonstration data

`app/fixtures/`, `deliverables/synthetic/`, the screenshots in `docs/screenshots/` and `notion-portfolio-package/screenshots/`, and the demo video are produced from **randomly generated data** (`src/inventoryiq/synthetic.py`, fixed seed). The data uses the M5 file layout and category names, but product ids start with `SYN_` and no values are derived from Walmart records. Provenance manifests (`*.manifest.json`) record the data source and a content hash for every published image and video.

## Software dependencies

Python and npm dependencies keep their own licenses (see `requirements*.txt` and `app/package-lock.json`).
