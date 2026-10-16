-- Business question: Do temporary price reductions lift unit sales, and by how much per category?
-- Approach: detect weeks where the OBSERVED shelf price is at least 5% below the item-store's
--           previous week (LAG), and compare average weekly units in those weeks with the item's
--           non-reduced weeks. Last two years of complete weeks only.
-- Skills: LAG window, date filtering, CTE chains, conditional aggregation.
-- Tables: prices, daily_sales, calendar, series, products

WITH complete_weeks AS (
    SELECT wm_yr_wk, MIN(date) AS week_start
    FROM calendar
    WHERE day <= (SELECT MAX(day) FROM daily_sales)
    GROUP BY wm_yr_wk HAVING COUNT(*) = 7
),
recent AS (
    SELECT * FROM complete_weeks
    WHERE week_start >= (SELECT MAX(week_start) FROM complete_weeks) - INTERVAL 2 YEAR
),
weekly_units AS (
    SELECT s.store_id, s.item_id, c.wm_yr_wk, SUM(d.units) AS units
    FROM daily_sales d
    JOIN calendar c ON c.day = d.day
    JOIN recent r ON r.wm_yr_wk = c.wm_yr_wk
    JOIN series s ON s.series_id = d.series_id
    WHERE s.in_model_scope
    GROUP BY ALL
),
priced AS (
    SELECT p.store_id, p.item_id, p.wm_yr_wk, p.sell_price,
           LAG(p.sell_price) OVER (PARTITION BY p.store_id, p.item_id ORDER BY p.wm_yr_wk) AS prev_price
    FROM prices p
    JOIN recent r ON r.wm_yr_wk = p.wm_yr_wk
),
joined AS (
    SELECT pr.cat_id, w.units,
           CASE WHEN p.prev_price > 0 AND p.sell_price <= 0.95 * p.prev_price THEN 'reduced' ELSE 'regular' END AS price_state
    FROM weekly_units w
    JOIN priced p USING (store_id, item_id, wm_yr_wk)
    JOIN products pr ON pr.item_id = w.item_id
)
SELECT
    cat_id,
    COUNT(*) FILTER (WHERE price_state = 'reduced') AS reduced_price_weeks,
    ROUND(AVG(units) FILTER (WHERE price_state = 'reduced'), 2) AS avg_units_reduced,
    ROUND(AVG(units) FILTER (WHERE price_state = 'regular'), 2) AS avg_units_regular,
    ROUND(100.0 * (AVG(units) FILTER (WHERE price_state = 'reduced') / NULLIF(AVG(units) FILTER (WHERE price_state = 'regular'), 0) - 1), 1) AS naive_lift_pct
FROM joined
GROUP BY cat_id
ORDER BY cat_id;
-- Note: a naive comparison; it does not control for item mix, seasonality or events.
