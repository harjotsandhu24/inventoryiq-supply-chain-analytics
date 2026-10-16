-- Business question: Which product-store combinations have poor forecast accuracy?
-- Approach: holdout (final 28 observed days, never used for selection) error of the per-series
--           selected method versus the seasonal-naive benchmark. WAPE is undefined when actual
--           demand is zero, so those rows are labelled rather than divided by zero.
-- Skills: conditional aggregation (FILTER), CTEs, NULLIF, window percent rank by category.
-- Tables: forecast_evaluation, series, products

WITH holdout AS (
    SELECT
        series_id,
        SUM(abs_err) FILTER (WHERE method = 'selected')        AS abs_err_selected,
        SUM(abs_err) FILTER (WHERE method = 'seasonal_naive')  AS abs_err_naive,
        SUM(err)     FILTER (WHERE method = 'selected')        AS err_selected,
        MAX(actual)  FILTER (WHERE method = 'selected')        AS actual_units,
        MAX(n_days)  FILTER (WHERE method = 'selected')        AS days
    FROM forecast_evaluation
    WHERE phase = 'holdout'
    GROUP BY series_id
),
scored AS (
    SELECT
        h.series_id,
        s.store_id,
        p.cat_id,
        s.pattern,
        h.actual_units,
        ROUND(h.abs_err_selected / NULLIF(h.days, 0), 3)              AS mae,
        ROUND(h.abs_err_selected / NULLIF(h.actual_units, 0), 3)      AS wape,
        ROUND(h.abs_err_naive / NULLIF(h.actual_units, 0), 3)         AS wape_seasonal_naive,
        ROUND(h.err_selected / NULLIF(h.actual_units, 0), 3)          AS bias
    FROM holdout h
    JOIN series s USING (series_id)
    JOIN products p ON p.item_id = s.item_id
    WHERE s.in_model_scope
)
SELECT
    *,
    CASE WHEN actual_units = 0 THEN 'undefined (no demand in holdout)'
         WHEN wape > wape_seasonal_naive THEN 'worse than naive benchmark'
         WHEN wape > 0.8 THEN 'poor'
         ELSE 'acceptable' END AS assessment,
    ROUND(PERCENT_RANK() OVER (PARTITION BY cat_id ORDER BY wape), 3) AS wape_percentile_in_category
FROM scored
WHERE actual_units >= 28            -- at least ~1 unit/day so WAPE is meaningful
ORDER BY wape DESC
LIMIT 25;
