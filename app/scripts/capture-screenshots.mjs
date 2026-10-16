// Captures genuine screenshots of the running application (start it first: npm run build && npm run start).
// Usage: node scripts/capture-screenshots.mjs [baseUrl] [outDir]
import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const base = process.argv[2] ?? "http://localhost:3000";
const out = process.argv[3] ?? join(process.cwd(), "..", "docs", "screenshots");
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });

const saved = [];
async function shot(name, url, prepare, fullPage = false) {
  await page.goto(base + url, { waitUntil: "networkidle" });
  await page.getByRole("heading", { level: 1 }).waitFor();
  if (prepare) await prepare();
  await page.waitForTimeout(600); // let charts finish layout
  await page.screenshot({ path: join(out, name), fullPage });
  saved.push(name);
  console.log("saved", name);
}

await shot("01-overview.png", "/");
await shot("02-forecast.png", "/forecasts", async () => {
  await page.getByTestId("forecast-chart").waitFor();
});
await shot("03-planner.png", "/planner", async () => {
  const first = page.locator("[data-testid=planner-table] tbody tr").first();
  await first.click();
  await page.getByTestId("detail-panel").waitFor();
});
await shot("03b-planner-detail-full.png", "/planner", async () => {
  await page.locator("[data-testid=planner-table] tbody tr").first().click();
  await page.getByTestId("detail-panel").waitFor();
}, true);
const ref = await (await fetch(base + "/data/reference_plan.json")).json();
const deferredId = Object.entries(ref.results).find(([, r]) => String(r.status).startsWith("Deferred"))?.[0];
if (deferredId) {
  await shot("03c-planner-deferred.png", `/planner?show=all&line=${encodeURIComponent(deferredId)}`, async () => {
    await page.getByTestId("detail-panel").waitFor();
  }, true);
}
await shot("04-scenario.png", "/scenarios?preset=limit", async () => {
  await page.getByTestId("comparison-table").waitFor();
});
await shot("04b-scenario-full.png", "/scenarios?preset=protect", async () => {
  await page.getByTestId("comparison-table").waitFor();
}, true);
await browser.close();

// Provenance manifest: which dataset each image shows, with a content hash, so audits can verify public images.
const manifest = await (await fetch(base + "/data/manifest.json")).json();
const files = {};
for (const f of saved) files[f] = createHash("sha256").update(readFileSync(join(out, f))).digest("hex");
writeFileSync(join(out, "screenshots.manifest.json"), JSON.stringify({
  dataSource: manifest.source, sourceLabel: manifest.sourceLabel, planningDate: manifest.planningDate,
  capturedWith: "app/scripts/capture-screenshots.mjs (Playwright, Chromium, 1440x900 @2x)", files,
}, null, 2));
console.log("wrote manifest for", Object.keys(files).length, "images from", manifest.source);
