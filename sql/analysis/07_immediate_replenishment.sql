-- Business question: Which products require immediate replenishment, and what should we buy?
-- Approach: lines at or below their reorder point, prioritised by risk tier and stockout
--           probability, with in-transit stock and the expected receipt date of a new order.
-- Skills: joins, CASE ordering, date arithmetic, running totals with window frames.
-- Tables: replenishment_recommendations, calendar, series, products, suppliers

WITH plan_date AS (
    SELECT MAX(date) + INTERVAL 1 DAY AS planning_date FROM calendar c
    WHERE c.day = (SELECT MAX(day) FROM daily_sales)
)
SELECT
    r.priority_rank,
    r.series_id,
    s.store_id,
    p.cat_id,
    r.risk,
    ROUND(100 * r.p_stockout_lead_time, 1) AS stockout_probability_pct,
    r.on_hand,
    r.on_order AS in_transit,
    ROUND(r.reorder_point, 1) AS reorder_point,
    r.final_qty AS order_units,
    r.order_value,
    r.status,
    (pd.planning_date + TO_DAYS(CAST(ROUND(r.lead_time) AS INTEGER)))::DATE AS expected_receipt_date,
    SUM(r.order_value) OVER (ORDER BY r.priority_rank ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_spend
FROM replenishment_recommendations r
CROSS JOIN plan_date pd
JOIN series s USING (series_id)
JOIN products p ON p.item_id = s.item_id
WHERE r.final_qty > 0
ORDER BY r.priority_rank;
