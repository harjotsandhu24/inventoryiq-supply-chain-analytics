-- Business question: Which items have the lowest modeled days of inventory coverage?
-- Approach: coverage = SIMULATED on-hand units / MODELED expected daily demand, compared with
--           the SIMULATED supplier lead time. Items whose stock runs out before a new order can
--           arrive are flagged. Zero-demand items are reported separately, never divided by zero.
-- Skills: joins, CASE logic, NULLIF-safe division, window ranking.
-- Tables: replenishment_recommendations, supplier_assumptions, suppliers, series, products

SELECT
    r.series_id,
    s.store_id,
    p.cat_id,
    sup.supplier_name,
    r.on_hand,
    r.on_order,
    ROUND(r.mu, 2) AS expected_daily_demand,
    ROUND(r.on_hand / NULLIF(r.mu, 0), 1) AS coverage_days,
    a.lead_time_mean AS lead_time_days,
    CASE
        WHEN r.mu = 0 THEN 'no forecast demand'
        WHEN r.on_hand / r.mu < a.lead_time_mean THEN 'runs out before a new order can arrive'
        WHEN r.on_hand / r.mu < a.lead_time_mean + 7 THEN 'runs out within one review after lead time'
        ELSE 'covered'
    END AS coverage_status,
    r.risk,
    RANK() OVER (ORDER BY r.on_hand / NULLIF(r.mu, 0) ASC NULLS LAST) AS coverage_rank
FROM replenishment_recommendations r
JOIN supplier_assumptions a USING (series_id)
JOIN suppliers sup ON sup.supplier_id = a.supplier_id
JOIN series s USING (series_id)
JOIN products p ON p.item_id = s.item_id
WHERE r.mu > 0
ORDER BY coverage_rank
LIMIT 25;
