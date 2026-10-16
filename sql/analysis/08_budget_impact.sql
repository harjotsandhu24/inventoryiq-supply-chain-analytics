-- Business question: How does a purchasing budget affect recommended orders?
-- Approach: (1) walk the unconstrained order list in priority order with a running total and show
--           which lines fit under several budget levels (a simplified, whole-line view of the
--           engine's greedy rule); (2) compare with the engine's Limit Spending scenario, which
--           also allows partial whole-case funding.
-- Skills: window running totals, CROSS JOIN parameter tables, conditional aggregation.
-- Tables: replenishment_recommendations, scenario_results

WITH ordered AS (
    SELECT
        series_id,
        priority_rank,
        risk,
        order_value,
        SUM(order_value) OVER (ORDER BY priority_rank ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_spend
    FROM replenishment_recommendations
    WHERE final_qty > 0
),
total AS (SELECT SUM(order_value) AS full_spend FROM ordered),
budgets AS (
    SELECT share, ROUND(share * full_spend, 2) AS budget
    FROM total, (VALUES (0.25), (0.50), (0.75), (1.00)) v(share)
),
whole_line_view AS (
    SELECT
        b.share,
        b.budget,
        COUNT(*) FILTER (WHERE o.running_spend <= b.budget) AS lines_funded,
        COUNT(*) FILTER (WHERE o.running_spend > b.budget) AS lines_not_funded,
        COUNT(*) FILTER (WHERE o.running_spend > b.budget AND o.risk = 'High') AS high_risk_not_funded,
        ROUND(COALESCE(SUM(o.order_value) FILTER (WHERE o.running_spend <= b.budget), 0), 2) AS spend
    FROM budgets b CROSS JOIN ordered o
    GROUP BY b.share, b.budget
)
SELECT 'whole-line running total' AS method, share AS budget_share, budget, lines_funded, lines_not_funded,
       high_risk_not_funded, spend, NULL AS expected_short_units
FROM whole_line_view
UNION ALL
SELECT 'engine scenario: ' || scenario_id, NULL, MAX(budget),
       COUNT(*) FILTER (WHERE final_qty > 0),
       COUNT(*) FILTER (WHERE status LIKE 'Deferred%'),
       NULL,
       ROUND(SUM(order_value), 2),
       ROUND(SUM(expected_short_units), 1)
FROM scenario_results
WHERE scenario_id IN ('balanced', 'limit', 'zero_budget')
GROUP BY scenario_id
ORDER BY method, budget_share;
