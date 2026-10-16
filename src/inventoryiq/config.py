"""Central configuration: paths, evaluation windows, and versioned assumptions.

Day indices follow the M5 convention: day 1 is ``d_1`` (2011-01-29). All
windows below are inclusive ranges of day indices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "reports"
DELIVERABLES_DIR = ROOT / "deliverables"
APP_DATA_DIR = ROOT / "app" / "public" / "data"
SQL_DIR = ROOT / "sql"

RAW_FILES = (
    "calendar.csv",
    "sales_train_evaluation.csv",
    "sales_train_validation.csv",
    "sell_prices.csv",
)

ID_COLUMNS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]

# Version of every simulated / assumed input. Bump when any assumption changes.
ASSUMPTIONS_VERSION = "2026.10-v1"
RANDOM_SEED = 20260101

HORIZON = 28
SEASON = 7


@dataclass(frozen=True)
class Windows:
    """Evaluation design expressed in day indices for a dataset with ``last_day`` observed days.

    The final ``HORIZON`` observed days form the untouched holdout. Five
    non-overlapping 28-day validation folds end on the day before the holdout.
    A separate set of three folds ends before the historical simulation starts,
    so the simulated forecast-informed policy is selected without seeing the
    simulation period.
    """

    last_day: int
    n_validation_folds: int = 5
    sim_days: int = 182
    n_sim_selection_folds: int = 3

    @property
    def holdout(self) -> tuple[int, int]:
        return (self.last_day - HORIZON + 1, self.last_day)

    @property
    def validation_folds(self) -> list[tuple[int, int]]:
        end = self.holdout[0] - 1
        folds = []
        for k in range(self.n_validation_folds, 0, -1):
            stop = end - (k - 1) * HORIZON
            folds.append((stop - HORIZON + 1, stop))
        return folds

    @property
    def simulation(self) -> tuple[int, int]:
        return (self.last_day - self.sim_days + 1, self.last_day)

    @property
    def sim_selection_folds(self) -> list[tuple[int, int]]:
        end = self.simulation[0] - 1
        folds = []
        for k in range(self.n_sim_selection_folds, 0, -1):
            stop = end - (k - 1) * HORIZON
            folds.append((stop - HORIZON + 1, stop))
        return folds

    @property
    def confirmation(self) -> tuple[int, int]:
        """Earlier 182-day window, separated from the main simulation by 182 days.

        Used to test the v2 policy revision on data that played no part in diagnosing v1.
        """
        end = self.simulation[0] - 1 - self.sim_days
        return (end - self.sim_days + 1, end)

    def selection_folds_before(self, start: int) -> list[tuple[int, int]]:
        end = start - 1
        return [
            (end - k * HORIZON + 1, end - (k - 1) * HORIZON)
            for k in range(self.n_sim_selection_folds, 0, -1)
        ]

    @property
    def future(self) -> tuple[int, int]:
        return (self.last_day + 1, self.last_day + HORIZON)


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    departments: tuple[str, ...]
    lead_time_mean: float  # days
    lead_time_sd: float  # days
    moq_cases: int  # minimum order quantity, expressed in cases
    order_cost: float  # $ per purchase-order line
    capacity_factor: float  # weekly capacity / average weekly volume of assigned lines
    on_time_rate: float  # informational; share of POs arriving within mean + 1 day


# Simulated supplier master. These are assumptions, not Walmart data.
SUPPLIERS: tuple[Supplier, ...] = (
    Supplier("SUP-01", "Dry Grocery Supplier", ("FOODS_1",), 5, 1.0, 1, 6.0, 1.6, 0.93),
    Supplier("SUP-02", "Packaged Foods Supplier", ("FOODS_2",), 6, 1.5, 1, 6.0, 1.6, 0.90),
    Supplier("SUP-03", "Regional Fresh & Staples DC", ("FOODS_3",), 3, 0.8, 1, 4.0, 1.5, 0.95),
    Supplier(
        "SUP-04",
        "Import Hobby Goods Supplier",
        ("HOBBIES_1", "HOBBIES_2"),
        14,
        4.0,
        2,
        9.0,
        1.8,
        0.74,
    ),
    Supplier(
        "SUP-05", "Household Essentials Supplier", ("HOUSEHOLD_1",), 7, 2.0, 1, 7.0, 1.6, 0.88
    ),
    Supplier("SUP-06", "Home Goods Supplier", ("HOUSEHOLD_2",), 10, 3.5, 1, 8.0, 1.6, 0.81),
)


@dataclass(frozen=True)
class FinancialAssumptions:
    """Simulated cost structure. Prices are observed; everything else is assumed."""

    gross_margin: dict[str, float] = field(
        default_factory=lambda: {"FOODS": 0.30, "HOUSEHOLD": 0.38, "HOBBIES": 0.42}
    )
    annual_holding_rate: float = 0.25  # share of unit cost per year
    shortage_penalty_multiplier: float = 1.5  # x unit gross margin per lost unit
    cost_basis_days: int = 364  # unit cost = median shelf price over this window x (1 - margin)


@dataclass(frozen=True)
class PolicySettings:
    service_level: float = 0.95  # target cycle service level
    review_period: int = 7  # days between reviews
    lead_time_shift: float = 0.0  # days added to every supplier mean lead time
    lead_time_sd_multiplier: float = 1.0
    budget: float | None = None  # $ per review; None = unconstrained
    intermittent_fallback: bool = True


# Basic (status quo) policy: days-of-cover min/max on a trailing 28-day average.
BASIC_POLICY = {"avg_window": 28, "min_days_after_lead_time": 14, "max_days_after_lead_time": 28}

# Demo scope used by the interactive application.
DEMO_STORES = ("CA_1", "CA_2")
DEMO_ITEMS_PER_STORE = 150
MODEL_STORES = ("CA_1", "CA_2")  # stores covered by the gradient-boosting model and simulation

FIN = FinancialAssumptions()
