// Shapes of the precomputed analytical artifacts in public/data (written by src/inventoryiq/exports.py).

export type Risk = "High" | "Medium" | "Low";

export interface Metrics {
  mae: number | null;
  wape: number | null;
  bias: number | null;
  mase: number | null;
  actual: number;
  days: number;
}

export interface InTransitPO {
  po: string;
  qty: number;
  orderDate: string;
  expectedDate: string;
}

export interface LineData {
  id: string;
  item: string;
  store: string;
  dept: string;
  cat: string;
  supplier: string;
  abc: "A" | "B" | "C";
  xyz: "X" | "Y" | "Z";
  pattern: string;
  intermittent: boolean;
  method: string;
  methodLabel: string;
  mu: number;
  sigma: number;
  ltMean: number;
  ltSd: number;
  orderCost: number;
  casePack: number;
  moq: number;
  unitCost: number;
  unitPrice: number;
  onHand: number;
  onOrder: number;
  units364: number;
  value364: number;
  inTransit: InTransitPO[];
  history: (number | null)[];
  holdout: Metrics | null;
  holdoutNaive: Metrics | null;
  validationMae: number | null;
}

export interface Settings {
  serviceLevel: number;
  reviewPeriod: number;
  leadTimeShift: number;
  leadTimeSdMultiplier: number;
  budget: number | null;
  intermittentFallback: boolean;
  holdingRate: number;
  shortageMultiplier: number;
  maxCycleDays: number | null;
}

export interface Preset {
  label: string;
  service_level: number;
  review_period: number;
  lead_time_shift: number;
  lead_time_sd_multiplier: number;
  budget_share: number | null;
}

export interface Manifest {
  source: "m5" | "synthetic";
  sourceLabel: string;
  generatedAt: string;
  assumptionsVersion: string;
  planningDay: number;
  planningDate: string;
  lastObservedDate: string;
  holdout: { start: string; end: string };
  future: { start: string; end: string };
  simulation: { start: string; end: string };
  validation: {
    series: number;
    items: number;
    stores: string[];
    observedDays: number;
    firstDate: string;
    lastObservedDate: string;
    errors: number;
    warnings: number;
  };
  demo: { lines: number; stores: string[]; categories: string[] };
  defaults: Settings;
  presets: Record<string, Preset>;
  capacity: Record<string, number>;
  financial: { grossMargin: Record<string, number>; holdingRate: number; shortageMultiplier: number };
}

export interface SeriesForecast {
  id: string;
  method: string;
  methodLabel: string;
  history: { start: string; values: (number | null)[] };
  holdout: {
    start: string;
    actual: (number | null)[];
    forecast: Record<string, (number | null)[]>;
    selected: (number | null)[];
    lo80: (number | null)[];
    hi80: (number | null)[];
    lo95: (number | null)[];
    hi95: (number | null)[];
  };
  future: {
    start: string;
    selected: (number | null)[];
    forecast: Record<string, (number | null)[]>;
    lo80: (number | null)[];
    hi80: (number | null)[];
    lo95: (number | null)[];
    hi95: (number | null)[];
  };
  metrics: Record<string, Metrics>;
  validationMae: Record<string, number | null>;
}

export interface EvalRow {
  method: string;
  method_label: string;
  series_windows: number;
  days: number;
  actual_units: number;
  mae: number;
  rmse: number;
  wape: number | null;
  bias: number | null;
  mase: number | null;
  cat_id?: string;
  pattern?: string;
}

export interface Evaluation {
  params: Record<string, number | null>;
  holdoutModelStores: EvalRow[];
  holdoutAllStores: EvalRow[];
  holdoutByCategory: EvalRow[];
  holdoutByPattern: EvalRow[];
  validationModelStores: EvalRow[];
  coverage: { method: string; method_label: string; days: number; coverage80: number; coverage95: number }[];
  coverageByPattern: { pattern: string; days: number; coverage80: number; coverage95: number }[];
  selectionCounts: { scope: string; selected_method: string; series: number }[];
  demoHoldoutByMethod: EvalRow[];
}

export interface SimSummary {
  policy: "basic" | "forecast_v1" | "forecast";
  policy_label: string;
  scope: "demo" | "model_stores";
  window: "main" | "confirmation";
  lines: number;
  days: number;
  demand_units: number;
  fulfilled_units: number;
  lost_units: number;
  fill_rate: number | null;
  cycle_service_level: number | null;
  stockout_days: number;
  lines_with_stockout: number;
  avg_inventory_units: number;
  avg_inventory_value: number;
  ending_inventory_value: number;
  purchase_orders: number;
  purchase_units: number;
  purchasing_spend: number;
  holding_cost: number;
  ordering_cost: number;
  shortage_penalty: number;
  modeled_total_cost: number;
}

export interface Simulation {
  window: { start: string; end: string; days: number };
  confirmationWindow: { start: string; end: string; days: number };
  policyLabels: Record<string, string>;
  windowLabels?: Record<string, string>;
  summary: SimSummary[];
  sensitivity: {
    scope: string;
    window: string;
    policy: string;
    margin_shift: number;
    shortage_multiplier: number;
    order_cost_multiplier: number;
    modeled_total_cost: number;
  }[];
  daily: { policy: string; date: string; inventoryValue: number; demand: number; lost: number }[];
}

export interface Supplier {
  supplier_id: string;
  supplier_name: string;
  departments: string;
  lead_time_mean_days: number;
  lead_time_sd_days: number;
  moq_cases: number;
  order_cost_per_line: number;
  capacity_units_per_week: number | null;
  on_time_rate_assumed: number;
}
