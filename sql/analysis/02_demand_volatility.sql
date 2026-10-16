-- Business question: Which products show the greatest demand volatility?
-- Approach: roll daily sales up to Walmart weeks over the last 52 complete weeks, compute the
--           coefficient of variation (CV) of weekly demand, and bucket items into XYZ classes.
--           Only weeks in which the item was listed for all 7 days are used, so
--           "not yet launched" is never mistaken for zero demand.
-- Skills: CTEs, date-to-week transformation, conditional aggregation, statistical aggregates, NTILE.
-- Tables: daily_sales, calendar, series, prices

WITH weeks AS (
    SELECT wm_yr_wk
    FROM calendar
    WHERE day <= (SELECT MAX(day) FROM daily_sales)
    GROUP BY wm_yr_wk
    HAVING COUNT(*) = 7
    ORDER BY wm_yr_wk DESC
    LIMIT 52
),
weekly AS (
    SELECT s.series_id, s.store_id, s.item_id, c.wm_yr_wk, SUM(d.units) AS units
    FROM daily_sales d
    JOIN calendar c ON c.day = d.day
    JOIN weeks w ON w.wm_yr_wk = c.wm_yr_wk
    JOIN series s ON s.series_id = d.series_id
    JOIN prices p ON p.store_id = s.store_id AND p.item_id = s.item_id AND p.wm_yr_wk = c.wm_yr_wk
    GROUP BY ALL
    HAVING COUNT(*) = 7
),
stats AS (
    SELECT series_id, store_id, item_id,
           COUNT(*) AS listed_weeks,
           AVG(units) AS mean_weekly_units,
           STDDEV_SAMP(units) AS sd_weekly_units,
           STDDEV_SAMP(units) / NULLIF(AVG(units), 0) AS weekly_cv,
           SUM(CASE WHEN units = 0 THEN 1 ELSE 0 END) AS zero_weeks
    FROM weekly
    GROUP BY ALL
    HAVING COUNT(*) >= 26
)
SELECT
    series_id,
    store_id,
    item_id,
    listed_weeks,
    ROUND(mean_weekly_units, 2) AS mean_weekly_units,
    ROUND(sd_weekly_units, 2) AS sd_weekly_units,
    ROUND(weekly_cv, 3) AS weekly_cv,
    zero_weeks,
    CASE WHEN weekly_cv IS NULL THEN 'Z (no demand)'
         WHEN weekly_cv <= 0.5 THEN 'X'
         WHEN weekly_cv <= 1.0 THEN 'Y'
         ELSE 'Z' END AS xyz_class,
    NTILE(10) OVER (ORDER BY weekly_cv DESC NULLS FIRST) AS volatility_decile
FROM stats
WHERE mean_weekly_units >= 1          -- ignore near-dead items whose CV is dominated by noise
ORDER BY weekly_cv DESC
LIMIT 25;
