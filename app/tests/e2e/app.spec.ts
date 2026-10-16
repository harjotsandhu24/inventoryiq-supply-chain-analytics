import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// These tests work against whichever dataset is in public/data (M5-derived or the synthetic fixture).

async function ready(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

const kpiNumber = async (page: Page, id: string) => Number((await page.getByTestId(id).locator("div").nth(1).innerText()).replace(/[^0-9.]/g, ""));

test.describe("navigation", () => {
  test("four main screens are reachable from the nav and marked as current", async ({ page }) => {
    await ready(page, "/");
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link")).toHaveCount(4);
    for (const [label, heading] of [
      ["Demand Forecasts", "Demand forecasts"],
      ["Replenishment Planner", "Replenishment planner"],
      ["Scenario Lab", "Scenario lab"],
      ["Overview", "Inventory risk overview"],
    ]) {
      await nav.getByRole("link", { name: label }).click();
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expect(nav.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
    }
  });

  test("browser back/forward and reload keep the selected product", async ({ page }) => {
    await ready(page, "/planner");
    const first = page.locator("[data-testid=planner-table] tbody tr").first();
    const id = await first.getAttribute("data-row-id");
    await first.click();
    await expect(page).toHaveURL(/line=/);
    await expect(page.getByTestId("detail-panel")).toBeVisible();
    await page.reload();
    await expect(page.getByTestId("detail-panel")).toContainText(id!.split("_").slice(0, -2).join("_"));
    await page.goBack();
    await expect(page.getByTestId("detail-panel")).toHaveCount(0);
    await page.goForward();
    await expect(page.getByTestId("detail-panel")).toBeVisible();
  });

  test("source badge labels the data honestly", async ({ page }) => {
    await ready(page, "/");
    await expect(page.getByTestId("source-badge")).toHaveText(/M5 sales · simulated inventory|Synthetic demo data/);
    await expect(page.getByText(/not Walmart (operations|records)/)).toBeVisible();
  });
});

test.describe("overview", () => {
  test("shows five KPIs without NaN or Infinity", async ({ page }) => {
    await ready(page, "/");
    await expect(page.getByTestId("kpis").locator("> div")).toHaveCount(5);
    const text = await page.locator("main").innerText();
    expect(text).not.toMatch(/NaN|Infinity|undefined/);
  });

  test("KPIs reconcile with the planner under the same filters", async ({ page }) => {
    await ready(page, "/");
    const store = await page.getByTestId("filter-store").locator("option").nth(1).getAttribute("value");
    await page.getByTestId("filter-store").selectOption(store!);
    await expect(page).toHaveURL(new RegExp(`store=${store}`));
    const needOrder = await kpiNumber(page, "kpi-orders");
    await page.getByTestId("review-purchases").click();
    await expect(page.getByRole("heading", { name: "Replenishment planner" })).toBeVisible();
    await expect(page.getByTestId("filter-store")).toHaveValue(store!);
    await expect(page.getByText(`${needOrder} products`, { exact: true })).toBeVisible();
  });

  test("search with no match shows a helpful empty state and reset works", async ({ page }) => {
    await ready(page, "/");
    await page.getByLabel("Search").fill("zzzz-no-such-product");
    await expect(page.getByText("No products match these filters")).toBeVisible();
    await page.getByRole("button", { name: "Reset filters" }).click();
    await expect(page.getByTestId("risk-table")).toBeVisible();
  });

  test("sorting by a column reorders the table", async ({ page }) => {
    await ready(page, "/");
    const table = page.getByTestId("risk-table");
    await table.getByRole("button", { name: /On hand/ }).click();
    const desc = await table.locator("tbody tr td:nth-child(5)").allInnerTexts();
    await table.getByRole("button", { name: /On hand/ }).click();
    const asc = await table.locator("tbody tr td:nth-child(5)").allInnerTexts();
    const n = (s: string[]) => s.map((x) => Number(x.replace(/,/g, "")));
    expect(n(desc)).toEqual([...n(desc)].sort((a, b) => b - a));
    expect(n(asc)).toEqual([...n(asc)].sort((a, b) => a - b));
  });

  test("clicking a risk row opens its purchasing calculation", async ({ page }) => {
    await ready(page, "/");
    await page.getByTestId("risk-table").locator("tbody tr").first().click();
    await expect(page.getByTestId("detail-panel")).toBeVisible();
    await expect(page.getByTestId("calc-table")).toContainText("Reorder point");
  });
});

test.describe("forecasts", () => {
  test("chart, labels and method comparison render for the selected product", async ({ page }) => {
    await ready(page, "/forecasts");
    await expect(page.getByTestId("forecast-chart")).toBeVisible();
    await expect(page.getByTestId("forecast-chart").locator("svg").first()).toBeVisible();
    await expect(page.getByText("Held-back actuals")).toBeVisible();
    await expect(page.getByText("80% prediction interval")).toBeVisible();
    await expect(page.getByTestId("selected-method")).not.toBeEmpty();
    await expect(page.getByTestId("method-table").locator("tbody tr")).not.toHaveCount(0);
    await expect(page.getByTestId("portfolio-table")).toContainText("Seasonal naive");
  });

  test("changing product updates the URL and chart; weekly view hides intervals", async ({ page }) => {
    await ready(page, "/forecasts");
    const select = page.getByTestId("fc-product");
    const second = await select.locator("option").nth(1).getAttribute("value");
    await select.selectOption(second!);
    await expect(page).toHaveURL(new RegExp(`line=${second}`));
    await page.getByRole("button", { name: "Weekly" }).click();
    await expect(page.getByText("80% prediction interval")).toHaveCount(0);
    await expect(page.getByText(/intervals apply to daily values only/)).toBeVisible();
  });

  test("switching store keeps a valid product selection", async ({ page }) => {
    await ready(page, "/forecasts");
    const stores = await page.getByTestId("fc-store").locator("option").allInnerTexts();
    await page.getByTestId("fc-store").selectOption(stores[stores.length - 1]);
    await expect(page.getByTestId("forecast-chart")).toBeVisible();
    await expect(page.getByTestId("fc-product")).not.toHaveValue("");
  });
});

test.describe("replenishment planner", () => {
  test("detail panel shows inputs, formulas and a reason tied to the numbers", async ({ page }) => {
    await ready(page, "/planner");
    await page.locator("[data-testid=planner-table] tbody tr").first().click();
    const panel = page.getByTestId("detail-panel");
    for (const label of ["Stock on hand", "Simulated", "Modeled", "Incoming orders", "Expected daily demand", "Safety stock", "Reorder point s", "Inventory position", "Recommended quantity", "Unit cost"]) {
      await expect(panel).toContainText(label);
    }
    const rop = (await panel.getByRole("row", { name: /Reorder point s/ }).locator("td").innerText()).trim();
    await expect(page.getByTestId("recommendation-summary")).toContainText(rop);
  });

  test("what-if service level recalculates the recommendation", async ({ page }) => {
    await ready(page, "/planner");
    await page.locator("[data-testid=planner-table] tbody tr").first().click();
    const before = await page.getByTestId("whatif-qty").innerText();
    await page.getByTestId("whatif-sl").fill("0.995");
    await expect(page.getByTestId("whatif-qty")).not.toHaveText(before);
    await page.getByRole("button", { name: "Reset what-if" }).click();
    await expect(page.getByTestId("whatif-qty")).toHaveText(before);
  });

  test("purchase list export matches the on-screen calculation", async ({ page }) => {
    await ready(page, "/planner");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    const boxes = page.locator("[data-testid=planner-table] tbody input[type=checkbox]:not([disabled])");
    await boxes.nth(0).check();
    await boxes.nth(1).check();
    await expect(page.getByTestId("purchase-list").locator("li")).toHaveCount(2);
    const totalText = await page.getByTestId("list-total").innerText();
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-list").click()]);
    const csv = readFileSync((await download.path())!, "utf8").trim().split("\n");
    expect(csv[0]).toContain("funded_qty");
    expect(csv).toHaveLength(3);
    const header = csv[0].split(",");
    const valueIdx = header.indexOf("order_value");
    const sum = csv.slice(1).reduce((a, line) => a + Number(line.split(",")[valueIdx]), 0);
    const shown = Number(totalText.split("·")[1].replace(/[^0-9.]/g, ""));
    expect(sum).toBeCloseTo(shown, 2);
    // list survives reload
    await page.reload();
    await expect(page.getByTestId("purchase-list").locator("li")).toHaveCount(2);
    await page.getByRole("button", { name: "Clear list" }).click();
    await expect(page.getByText("Your purchase list is empty")).toBeVisible();
  });

  test("table export has one row per visible product", async ({ page }) => {
    await ready(page, "/planner");
    const countText = await page.getByText(/^\d+ products$/).innerText();
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-all").click()]);
    const lines = readFileSync((await download.path())!, "utf8").trim().split("\n");
    expect(lines.length - 1).toBe(Number(countText.split(" ")[0]));
  });

  test("supplier capacity is explained, and deferred lines show the capacity left", async ({ page }) => {
    await ready(page, "/planner");
    await expect(page.getByTestId("capacity-table")).toBeVisible();
    await expect(page.getByTestId("capacity-explainer")).toContainText("Capacity goes to the highest-risk lines first");
    const ref = await (await page.request.get("/data/reference_plan.json")).json();
    const deferred = Object.entries(ref.results as Record<string, { status: string }>).find(([, r]) => r.status === "Deferred: supplier capacity");
    test.skip(!deferred, "no capacity-deferred line in this dataset");
    await ready(page, `/planner?show=all&line=${deferred![0]}`);
    await expect(page.getByTestId("capacity-callout")).toBeVisible();
    await expect(page.getByTestId("recommendation-summary")).toContainText(/units left for this review after higher-priority lines/);
  });

  test("filters with no results show an empty state", async ({ page }) => {
    await ready(page, "/planner?q=zzzz-none");
    await expect(page.getByText(/No products need an order|No products match/)).toBeVisible();
  });

  test("unknown product in the URL shows an error message", async ({ page }) => {
    await ready(page, "/planner?line=NOT_A_PRODUCT");
    await expect(page.getByText(/is not in the demo scope/)).toBeVisible();
  });

  test("keyboard: rows open with Enter", async ({ page }) => {
    await ready(page, "/planner");
    const row = page.locator("[data-testid=planner-table] tbody tr").first();
    await row.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("detail-panel")).toBeVisible();
    await page.getByRole("button", { name: "Close calculation panel" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("detail-panel")).toHaveCount(0);
  });
});

test.describe("scenario lab", () => {
  const cell = (page: Page, measure: string, col: number) => page.getByTestId("comparison-table").getByRole("row", { name: new RegExp(measure) }).locator("td").nth(col);

  test("presets change results; reset returns to the baseline", async ({ page }) => {
    await ready(page, "/scenarios");
    await expect(cell(page, "Modeled annual total cost", 2)).toHaveText("no change");
    await page.getByTestId("preset-protect").click();
    await expect(page.getByTestId("sl-value")).toHaveText("99.0%");
    await expect(cell(page, "Modeled annual holding cost", 2)).not.toHaveText("no change");
    await page.getByTestId("preset-limit").click();
    await expect(page.getByTestId("budget")).not.toHaveValue("");
    await page.getByTestId("reset").click();
    await expect(page.getByTestId("preset-balanced")).toHaveAttribute("aria-checked", "true");
    await expect(cell(page, "Modeled annual total cost", 2)).toHaveText("no change");
  });

  test("limit spending keeps spend under the budget", async ({ page }) => {
    await ready(page, "/scenarios?preset=limit");
    const budget = Number(await page.getByTestId("budget").inputValue());
    const spend = Number((await cell(page, "Purchase spend", 1).innerText()).replace(/[^0-9.]/g, ""));
    expect(spend).toBeLessThanOrEqual(budget + 1);
  });

  test("moving a slider switches to a custom scenario and is reproducible after reload", async ({ page }) => {
    await ready(page, "/scenarios?preset=protect");
    await page.getByTestId("lt-slider").fill("7");
    await expect(page.getByTestId("preset-custom")).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("sl-value")).toHaveText("99.0%"); // preset values carried into the custom scenario
    const spend = await cell(page, "Purchase spend", 1).innerText();
    await page.reload();
    await expect(cell(page, "Purchase spend", 1)).toHaveText(spend);
  });

  test("invalid budget shows a validation message", async ({ page }) => {
    await ready(page, "/scenarios");
    await page.getByTestId("budget-unlimited").uncheck();
    await page.getByTestId("budget").fill("-50");
    await expect(page.getByText("Enter zero or a positive amount")).toBeVisible();
    await expect(page.getByTestId("budget")).toHaveAttribute("aria-invalid", "true");
  });

  test("scenario export includes the assumptions and one row per product", async ({ page }) => {
    await ready(page, "/scenarios?preset=protect");
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-scenario").click()]);
    const lines = readFileSync((await download.path())!, "utf8").trim().split("\n");
    expect(lines[0]).toContain("service_level");
    expect(lines[1]).toContain("0.99");
    expect(lines.length).toBeGreaterThan(10);
  });

  test("historical backtest lists all three policies for both windows", async ({ page }) => {
    await ready(page, "/scenarios");
    await expect(page.getByTestId("evidence-labels")).toContainText("not independent");
    await expect(page.getByText(/Confirmation window \(held out from v2 design\)/)).toBeVisible();
    const tables = page.getByTestId("backtest-table");
    await expect(tables).toHaveCount(2);
    for (const t of await tables.all()) await expect(t.locator("tbody tr")).toHaveCount(3);
    await expect(page.getByTestId("sensitivity-table")).not.toContainText("NaN");
  });
});
