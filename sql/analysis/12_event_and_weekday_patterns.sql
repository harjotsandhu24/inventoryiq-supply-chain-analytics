-- Business question: How much do weekdays and calendar events change daily demand?
-- Approach: average store-category daily units by weekday and by event type relative to the
--           store-category's overall daily average (date transformations on the calendar).
-- Skills: date functions (dayname, year), joins, GROUPING SETS, window averages.
-- Tables: daily_sales, calendar, series, products

WITH daily AS (
    SELECT s.store_id, p.cat_id, c.date, dayname(c.date) AS weekday, year(c.date) AS yr,
           COALESCE(c.event_type_1, 'No event') AS event_type, SUM(d.units) AS units
    FROM daily_sales d
    JOIN calendar c ON c.day = d.day
    JOIN series s ON s.series_id = d.series_id
    JOIN products p ON p.item_id = s.item_id
    WHERE s.in_model_scope AND year(c.date) >= 2014
    GROUP BY ALL
),
indexed AS (
    SELECT *, units / AVG(units) OVER (PARTITION BY store_id, cat_id) AS demand_index
    FROM daily
)
SELECT
    COALESCE(weekday, 'All weekdays') AS weekday,
    COALESCE(event_type, 'All days') AS event_type,
    cat_id,
    COUNT(*) AS store_days,
    ROUND(AVG(demand_index), 3) AS avg_demand_index   -- 1.00 = average day for that store and category
FROM indexed
GROUP BY GROUPING SETS ((weekday, cat_id), (event_type, cat_id))
ORDER BY cat_id, event_type NULLS FIRST, avg_demand_index DESC;
