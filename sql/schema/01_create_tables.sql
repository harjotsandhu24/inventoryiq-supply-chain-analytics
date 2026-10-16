-- InventoryIQ analytical schema (DuckDB).
-- Data lineage tags used in comments:
--   OBSERVED  = loaded from the M5 source files without modification
--   DERIVED   = calculated directly from observed data
--   MODELED   = forecasts and planning calculations
--   SIMULATED = assumed suppliers, inventory, purchase orders, costs

-- OBSERVED ------------------------------------------------------------------
CREATE TABLE stores (
    store_id      VARCHAR PRIMARY KEY,
    state_id      VARCHAR NOT NULL
);

CREATE TABLE products (
    item_id       VARCHAR PRIMARY KEY,
    dept_id       VARCHAR NOT NULL,
    cat_id        VARCHAR NOT NULL
);

CREATE TABLE calendar (
    day           INTEGER PRIMARY KEY,          -- M5 d_N index
    date          DATE NOT NULL UNIQUE,
    wm_yr_wk      INTEGER NOT NULL,
    weekday       VARCHAR NOT NULL,
    wday          TINYINT NOT NULL,
    month         TINYINT NOT NULL,
    year          SMALLINT NOT NULL,
    event_name_1  VARCHAR,
    event_type_1  VARCHAR,
    event_name_2  VARCHAR,
    event_type_2  VARCHAR,
    snap_ca       TINYINT NOT NULL,
    snap_tx       TINYINT NOT NULL,
    snap_wi       TINYINT NOT NULL
);

-- One row per product-store combination (DERIVED attributes added).
CREATE TABLE series (
    series_id               VARCHAR PRIMARY KEY,
    item_id                 VARCHAR NOT NULL REFERENCES products (item_id),
    store_id                VARCHAR NOT NULL REFERENCES stores (store_id),
    availability_start_day  INTEGER NOT NULL,   -- DERIVED: first day with a listed price
    pattern                 VARCHAR NOT NULL,   -- DERIVED: smooth / erratic / intermittent / lumpy
    in_model_scope          BOOLEAN NOT NULL,   -- covered by gradient boosting + simulation
    in_demo                 BOOLEAN NOT NULL    -- one of the application's sampled lines
);

-- OBSERVED daily unit sales (long format). Uniqueness of (series_id, day) is
-- verified by 02_integrity_checks.sql rather than an index, to keep the build light.
CREATE TABLE daily_sales (
    series_id     VARCHAR NOT NULL,
    day           INTEGER NOT NULL,
    units         INTEGER NOT NULL
);

CREATE TABLE prices (
    store_id      VARCHAR NOT NULL REFERENCES stores (store_id),
    item_id       VARCHAR NOT NULL REFERENCES products (item_id),
    wm_yr_wk      INTEGER NOT NULL,
    sell_price    DECIMAL(10, 2) NOT NULL,
    PRIMARY KEY (store_id, item_id, wm_yr_wk)
);

-- SIMULATED -----------------------------------------------------------------
CREATE TABLE suppliers (
    supplier_id            VARCHAR PRIMARY KEY,
    supplier_name          VARCHAR NOT NULL,
    departments            VARCHAR NOT NULL,
    lead_time_mean_days    DOUBLE NOT NULL CHECK (lead_time_mean_days > 0),
    lead_time_sd_days      DOUBLE NOT NULL CHECK (lead_time_sd_days >= 0),
    moq_cases              INTEGER NOT NULL CHECK (moq_cases >= 1),
    order_cost_per_line    DECIMAL(10, 2) NOT NULL,
    capacity_factor        DOUBLE NOT NULL,
    on_time_rate_assumed   DOUBLE NOT NULL,
    assumptions_version    VARCHAR NOT NULL
);

CREATE TABLE supplier_assumptions (
    series_id        VARCHAR PRIMARY KEY REFERENCES series (series_id),
    supplier_id      VARCHAR NOT NULL REFERENCES suppliers (supplier_id),
    case_pack        INTEGER NOT NULL CHECK (case_pack >= 1),
    moq_units        INTEGER NOT NULL CHECK (moq_units >= case_pack),
    unit_price       DECIMAL(10, 2) NOT NULL CHECK (unit_price > 0),   -- OBSERVED median shelf price
    unit_cost        DECIMAL(10, 2) NOT NULL CHECK (unit_cost > 0),    -- SIMULATED
    gross_margin     DOUBLE NOT NULL,
    order_cost       DECIMAL(10, 2) NOT NULL,
    lead_time_mean   DOUBLE NOT NULL,
    lead_time_sd     DOUBLE NOT NULL
);

CREATE TABLE inventory_ledger (
    scope       VARCHAR NOT NULL,     -- demo | model_stores
    policy      VARCHAR NOT NULL,     -- basic | forecast_v1 | forecast (v2)
    series_id   VARCHAR NOT NULL,
    day         INTEGER NOT NULL,
    opening     BIGINT NOT NULL CHECK (opening >= 0),
    receipts    BIGINT NOT NULL CHECK (receipts >= 0),
    demand      BIGINT NOT NULL CHECK (demand >= 0),
    fulfilled   BIGINT NOT NULL CHECK (fulfilled >= 0),
    lost        BIGINT NOT NULL CHECK (lost >= 0),
    closing     BIGINT NOT NULL CHECK (closing >= 0),
    on_order    BIGINT NOT NULL CHECK (on_order >= 0),
    ordered     BIGINT NOT NULL CHECK (ordered >= 0),
    PRIMARY KEY (scope, policy, series_id, day)
);

CREATE TABLE purchase_orders (
    scope                 VARCHAR NOT NULL,
    po_id                 VARCHAR NOT NULL,
    policy                VARCHAR NOT NULL,
    series_id             VARCHAR NOT NULL,
    order_day             INTEGER NOT NULL,
    quantity              INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost             DECIMAL(10, 2) NOT NULL,
    supplier_id           VARCHAR NOT NULL REFERENCES suppliers (supplier_id),
    lead_time_realised    INTEGER NOT NULL CHECK (lead_time_realised >= 1),
    expected_arrival_day  INTEGER NOT NULL,
    arrival_day           INTEGER NOT NULL,
    status                VARCHAR NOT NULL,
    PRIMARY KEY (scope, po_id),
    UNIQUE (scope, policy, series_id, order_day)
);

-- MODELED -------------------------------------------------------------------
CREATE TABLE forecast_results (
    series_id   VARCHAR NOT NULL,
    phase       VARCHAR NOT NULL,       -- holdout | future
    day         INTEGER NOT NULL,
    method      VARCHAR NOT NULL,
    forecast    DOUBLE NOT NULL CHECK (forecast >= 0),
    lo80        DOUBLE,
    hi80        DOUBLE,
    lo95        DOUBLE,
    hi95        DOUBLE,
    PRIMARY KEY (series_id, phase, day, method)
);

CREATE TABLE forecast_evaluation (
    series_id   VARCHAR NOT NULL,
    phase       VARCHAR NOT NULL,       -- validation | holdout
    fold        INTEGER NOT NULL,       -- 0-4 for validation, -1 for holdout
    method      VARCHAR NOT NULL,
    n_days      INTEGER NOT NULL,
    abs_err     DOUBLE NOT NULL,
    err         DOUBLE NOT NULL,
    actual      DOUBLE NOT NULL,
    forecast    DOUBLE NOT NULL,
    sq_err      DOUBLE NOT NULL,
    mase_scale  DOUBLE,
    PRIMARY KEY (series_id, phase, fold, method)
);

CREATE TABLE replenishment_recommendations (
    series_id              VARCHAR PRIMARY KEY,
    planning_day           INTEGER NOT NULL,
    supplier_id            VARCHAR NOT NULL REFERENCES suppliers (supplier_id),
    mu                     DOUBLE NOT NULL,
    sigma                  DOUBLE NOT NULL,
    lead_time              DOUBLE NOT NULL,
    protection_period      DOUBLE NOT NULL,
    safety_stock           DOUBLE NOT NULL,
    reorder_point          DOUBLE NOT NULL,
    order_up_to            DOUBLE NOT NULL,
    on_hand                INTEGER NOT NULL CHECK (on_hand >= 0),
    on_order               INTEGER NOT NULL CHECK (on_order >= 0),
    inventory_position     DOUBLE NOT NULL,
    coverage_days          DOUBLE,
    p_stockout_lead_time   DOUBLE NOT NULL,
    risk                   VARCHAR NOT NULL,
    recommended_qty        INTEGER NOT NULL CHECK (recommended_qty >= 0),
    final_qty              INTEGER NOT NULL CHECK (final_qty >= 0),
    status                 VARCHAR NOT NULL,
    unit_cost              DECIMAL(10, 2) NOT NULL,
    order_value            DECIMAL(12, 2) NOT NULL,
    priority_rank          INTEGER NOT NULL,
    abc                    VARCHAR NOT NULL,
    xyz                    VARCHAR NOT NULL,
    reason                 VARCHAR NOT NULL
);

CREATE TABLE scenario_results (
    scenario_id            VARCHAR NOT NULL,
    series_id              VARCHAR NOT NULL,
    service_level          DOUBLE NOT NULL,
    review_period          INTEGER NOT NULL,
    lead_time_shift        DOUBLE NOT NULL,
    lead_time_sd_mult      DOUBLE NOT NULL,
    budget                 DOUBLE,
    reorder_point          DOUBLE NOT NULL,
    final_qty              INTEGER NOT NULL,
    order_value            DECIMAL(12, 2) NOT NULL,
    status                 VARCHAR NOT NULL,
    expected_short_units   DOUBLE NOT NULL,
    annual_total_cost      DOUBLE NOT NULL,
    PRIMARY KEY (scenario_id, series_id)
);

CREATE TABLE simulation_summary (
    scope                  VARCHAR NOT NULL,
    "window"               VARCHAR NOT NULL,     -- main | confirmation
    window_start_day       INTEGER NOT NULL,
    window_end_day         INTEGER NOT NULL,
    policy                 VARCHAR NOT NULL,     -- basic | forecast_v1 | forecast (v2)
    policy_label           VARCHAR NOT NULL,
    lines                  INTEGER NOT NULL,
    days                   INTEGER NOT NULL,
    demand_units           DOUBLE NOT NULL,
    fulfilled_units        DOUBLE NOT NULL,
    lost_units             DOUBLE NOT NULL,
    fill_rate              DOUBLE,
    cycle_service_level    DOUBLE,
    stockout_days          INTEGER NOT NULL,
    lines_with_stockout    INTEGER NOT NULL,
    avg_inventory_units    DOUBLE NOT NULL,
    avg_inventory_value    DOUBLE NOT NULL,
    ending_inventory_value DOUBLE NOT NULL,
    ending_on_order_value  DOUBLE NOT NULL,
    purchase_orders        INTEGER NOT NULL,
    purchase_units         DOUBLE NOT NULL,
    purchasing_spend       DOUBLE NOT NULL,
    holding_cost           DOUBLE NOT NULL,
    ordering_cost          DOUBLE NOT NULL,
    shortage_penalty       DOUBLE NOT NULL,
    modeled_total_cost     DOUBLE NOT NULL,
    PRIMARY KEY (scope, "window", policy)
);
