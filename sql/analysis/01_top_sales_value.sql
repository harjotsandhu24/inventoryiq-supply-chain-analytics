-- Business question: Which products generate the highest historical sales value?
-- Approach: value each day's OBSERVED units at that week's OBSERVED shelf price (calendar -> week
--           -> price join), aggregate the final 364 observed days, and rank within each store.
-- Skills: joins, CTEs, date filtering, aggregation, window ranking.
-- Tables: daily_sales, calendar, series, prices

WITH last_year AS (
    SELECT MAX(day) - 363 AS first_day, MAX(day) AS last_day FROM daily_sales
),
valued AS (
    SELECT
        s.store_id,
        s.item_id,
        pr.cat_id,
        d.units,
        d.units * p.sell_price AS sales_value
    FROM daily_sales d
    JOIN last_year ly ON d.day BETWEEN ly.first_day AND ly.last_day
    JOIN calendar c ON c.day = d.day
    JOIN series s ON s.series_id = d.series_id
    JOIN products pr ON pr.item_id = s.item_id
    JOIN prices p
      ON p.store_id = s.store_id AND p.item_id = s.item_id AND p.wm_yr_wk = c.wm_yr_wk
),
by_product AS (
    SELECT store_id, item_id, cat_id,
           SUM(units) AS units_364d,
           ROUND(SUM(sales_value), 2) AS sales_value_364d
    FROM valued
    GROUP BY store_id, item_id, cat_id
)
SELECT
    store_id,
    item_id,
    cat_id,
    units_364d,
    sales_value_364d,
    RANK() OVER (PARTITION BY store_id ORDER BY sales_value_364d DESC) AS rank_in_store,
    ROUND(100.0 * sales_value_364d / SUM(sales_value_364d) OVER (PARTITION BY store_id), 3) AS pct_of_store_value
FROM by_product
QUALIFY rank_in_store <= 10
ORDER BY store_id, rank_in_store;
