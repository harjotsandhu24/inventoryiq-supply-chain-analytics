-- Business question: How is value concentrated across the demo assortment, and how variable is it?
-- Approach: ABC/XYZ cross-tab of demo lines with value share and current risk counts.
-- Skills: conditional aggregation, PIVOT-style FILTER, window share of total.
-- Tables: replenishment_recommendations, supplier_assumptions

WITH lines AS (
    SELECT r.abc, r.xyz, r.risk, r.final_qty, r.order_value, r.mu * a.unit_price * 364 AS annual_value_forecast
    FROM replenishment_recommendations r
    JOIN supplier_assumptions a USING (series_id)
)
SELECT
    abc,
    COUNT(*) FILTER (WHERE xyz = 'X') AS x_lines,
    COUNT(*) FILTER (WHERE xyz = 'Y') AS y_lines,
    COUNT(*) FILTER (WHERE xyz = 'Z') AS z_lines,
    COUNT(*) AS lines,
    ROUND(100.0 * SUM(annual_value_forecast) / SUM(SUM(annual_value_forecast)) OVER (), 1) AS pct_forecast_value,
    COUNT(*) FILTER (WHERE risk = 'High') AS high_risk_lines,
    ROUND(SUM(order_value), 2) AS recommended_spend
FROM lines
GROUP BY abc
ORDER BY abc;
