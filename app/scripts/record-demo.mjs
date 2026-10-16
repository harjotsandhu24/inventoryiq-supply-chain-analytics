// Records a SILENT, captioned walkthrough of the running app with Playwright's built-in video capture.
// Public version: run the app on the synthetic demo data (npm run data:demo, then restart the server).
// Usage: node scripts/record-demo.mjs [baseUrl] [outFile]
import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const base = process.argv[2] ?? "http://localhost:3000";
const target = process.argv[3] ?? join(process.cwd(), "..", "demo-video", "inventoryiq_demo_synthetic.webm");
const tmp = join(dirname(target), ".recording");
rmSync(tmp, { recursive: true, force: true });
mkdirSync(tmp, { recursive: true });

const manifest = await (await fetch(`${base}/data/manifest.json`)).json();
const label = manifest.source === "synthetic" ? "synthetic demo data" : "M5 sales, simulated inventory";

const size = { width: 1440, height: 900 };
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: size, recordVideo: { dir: tmp, size } });
const page = await context.newPage();

async function caption(text) {
  await page.evaluate((t) => {
    let el = document.getElementById("__demo_caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "__demo_caption";
      Object.assign(el.style, {
        position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: "9999",
        background: "rgba(23,45,71,0.94)", color: "#fff", padding: "10px 20px", borderRadius: "8px",
        font: "600 19px 'Segoe UI', system-ui, sans-serif", maxWidth: "82%", textAlign: "center",
        boxShadow: "0 2px 12px rgba(0,0,0,0.18)",
      });
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
}
const wait = (ms) => page.waitForTimeout(ms);
const smoothScroll = (locator) => locator.evaluate((el) => el.scrollIntoView({ behavior: "smooth", block: "center" }));

// 1. Overview
await page.goto(base + "/", { waitUntil: "networkidle" });
await page.getByTestId("kpis").waitFor();
await caption(`InventoryIQ overview: ${manifest.demo.lines} product-store lines (${label})`);
await wait(4000);
// 2. Identify a product at risk
await page.getByTestId("kpi-risk").hover();
await caption("These lines are likely to run out before a new order could arrive");
await wait(3500);
const first = page.locator("[data-testid=risk-table] tbody tr").first();
await first.hover();
await caption("The highest-risk product is at the top of the table");
await wait(2500);
// 3-4. Open the planner with that product selected
await first.click();
await page.getByTestId("detail-panel").waitFor();
await caption("Replenishment Planner: the selected product's purchase recommendation");
await wait(3500);
// 5. Recommendation
await page.getByTestId("recommendation-summary").hover();
await caption("Recommended quantity, cost, expected receipt date and the reason");
await wait(4000);
// 6. Mathematical reasoning
await smoothScroll(page.getByTestId("calc-table"));
await caption("Safety stock, reorder point, order-up-to level and case-pack rounding, step by step");
await wait(5000);
// 7-8. Change assumptions and watch the recalculation
await smoothScroll(page.getByTestId("whatif-sl"));
await caption("What if we target 99.5% availability?");
await wait(1500);
await page.getByTestId("whatif-sl").fill("0.995");
await wait(3000);
await caption("...and the supplier takes 5 days longer? The recommendation recalculates instantly");
await page.getByTestId("whatif-lt").fill("5");
await wait(4000);
// 9. Scenario Lab
await page.goto(base + "/scenarios", { waitUntil: "networkidle" });
await page.getByTestId("comparison-table").waitFor();
await caption("Scenario Lab: every scenario is compared with the fixed Balanced plan");
await wait(3500);
// 10. Compare trade-offs
await page.getByTestId("preset-protect").click();
await caption("Protect Availability: more safety stock, higher holding cost, lower shortage penalty");
await wait(5000);
await page.getByTestId("preset-limit").click();
await caption("Limit Spending: the budget defers lower-priority orders, so expected shortages rise");
await wait(5000);
await smoothScroll(page.getByTestId("backtest-table").first());
await caption("Historical backtest: policies compared on identical demand, lead times and costs");
await wait(5000);
await context.close();
await browser.close();

const recorded = readdirSync(tmp).filter((f) => f.endsWith(".webm"));
if (recorded.length !== 1) throw new Error(`expected one recording, found ${recorded.length}`);
renameSync(join(tmp, recorded[0]), target);
rmSync(tmp, { recursive: true, force: true });
writeFileSync(`${target}.manifest.json`, JSON.stringify({
  dataSource: manifest.source, sourceLabel: manifest.sourceLabel,
  recordedWith: "app/scripts/record-demo.mjs (Playwright video, 1440x900, silent with captions)",
  sha256: createHash("sha256").update(readFileSync(target)).digest("hex"),
}, null, 2));
console.log("saved", target);
