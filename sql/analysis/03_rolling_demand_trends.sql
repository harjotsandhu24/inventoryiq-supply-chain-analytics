-- Business question: Is demand for each demo product accelerating or slowing?
-- Approach: 7- and 28-day rolling averages via window frames, compared with the same 28-day
--           window one year (364 days, same weekday alignment) earlier.
-- Skills: rolling window frames, LAG, date arithmetic, CTEs.
-- Tables: daily_sales, calendar, series

WITH demo AS (
    SELECT series_id FROM series WHERE in_demo
),
daily AS (
    SELECT d.series_id, d.day, c.date, d.units
    FROM daily_sales d
    JOIN demo USING (series_id)
    JOIN calendar c ON c.day = d.day
),
rolling AS (
    SELECT
        series_id,
        day,
        date,
        units,
        AVG(units) OVER w7 AS avg_7d,
        AVG(units) OVER w28 AS avg_28d,
        COUNT(*) OVER w28 AS days_in_28d_window
    FROM daily
    WINDOW w7 AS (PARTITION BY series_id ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
           w28 AS (PARTITION BY series_id ORDER BY day ROWS BETWEEN 27 PRECEDING AND CURRENT ROW)
),
with_prior AS (
    SELECT *,
           LAG(avg_28d, 364) OVER (PARTITION BY series_id ORDER BY day) AS avg_28d_last_year,
           date - INTERVAL 364 DAY AS comparison_date
    FROM rolling
)
SELECT
    series_id,
    date AS as_of_date,
    comparison_date::DATE AS compared_with,
    ROUND(avg_7d, 2) AS avg_7d,
    ROUND(avg_28d, 2) AS avg_28d,
    ROUND(avg_28d_last_year, 2) AS avg_28d_last_year,
    ROUND(100.0 * (avg_28d - avg_28d_last_year) / NULLIF(avg_28d_last_year, 0), 1) AS yoy_change_pct,
    CASE
        WHEN avg_28d_last_year IS NULL OR avg_28d_last_year = 0 THEN 'insufficient history'
        WHEN avg_28d > 1.2 * avg_28d_last_year THEN 'growing'
        WHEN avg_28d < 0.8 * avg_28d_last_year THEN 'declining'
        ELSE 'stable'
    END AS trend
FROM with_prior
WHERE day = (SELECT MAX(day) FROM daily_sales)
  AND days_in_28d_window = 28
ORDER BY yoy_change_pct DESC NULLS LAST;
