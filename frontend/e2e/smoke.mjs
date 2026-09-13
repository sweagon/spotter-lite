import { chromium } from "/home/morpheus/Projects/spotter/venv/lib/python3.11/site-packages/playwright/driver/package/index.mjs";
import { existsSync } from "node:fs";

const base = process.env.BASE_URL || "http://localhost:5173";
const pw = process.env.PW_BIN || null;
const results = [];
let pass = 0, fail = 0;

function executablePath() {
  if (pw && existsSync(pw)) return pw;
  const candidates = [
    "/home/morpheus/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
    "/root/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
    "/home/morpheus/.cache/ms-playwright/chromium/chrome-linux/chrome",
  ];
  for (const c of candidates) if (existsSync(c)) return c;
  return undefined;
}

async function check(name, fn) {
  try {
    await fn();
    results.push(`PASS ${name}`);
    pass += 1;
  } catch (e) {
    results.push(`FAIL ${name}: ${e.message.split("\n")[0]}`);
    fail += 1;
  }
}

const browser = await chromium.launch({ executablePath: executablePath() });
const vw = (process.env.PW_VIEWPORT || "1480x1000").split("x").map(Number);
const page = await browser.newPage({ viewport: { width: vw[0], height: vw[1] } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => {
  if (m.type() === "error" && !/401|404|Failed to load resource/.test(m.text())) {
    errors.push(m.text().slice(0, 200));
  }
});

async function login(u, pathRe) {
  await page.goto(`${base}/login`);
  await page.fill('input[autocomplete="username"]', u);
  await page.fill('input[autocomplete="current-password"]', "spotter123");
  await page.click('button[type="submit"]');
  await page.waitForURL(new RegExp("^" + pathRe + "(/|$)"), { timeout: 10000 });
}

/* ---------- driver cab ---------- */
await check("driver login lands on the cab", async () => {
  await login("danton", "http://localhost:5173/$");
  await page.waitForSelector(".duty-card", { timeout: 8000 });
});

await check("signalling Driving draws the live RODS sheet", async () => {
  // wait until today's duty status is fully fetched so the buttons reflect
  // reality (on a fresh mount they briefly show enabled while status loads).
  await page.waitForSelector(".live-log-wrap .sheet, .live-log-wrap .empty", { timeout: 8000 });
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
  // self-heal: a previous run may have left the driver already Driving. end
  // that shift so the Driving tap below always opens the confirm sheet.
  if (await page.locator(".duty-btn--driving.duty-btn--active").count()) {
    await page.click(".duty-btn--off_duty");
    await page.waitForSelector(".duty-confirm", { timeout: 5000 });
    await page.click(".duty-confirm .btn-mini--solid");
    await page.waitForFunction(() => {
      const b = document.querySelector(".duty-btn--driving");
      return b && !b.disabled;
    }, { timeout: 5000 });
  }
  await page.click(".duty-btn--driving.duty-btn:not(.duty-btn--active)");
  await page.waitForSelector(".duty-confirm", { timeout: 5000 });
  await page.click(".duty-confirm .btn-mini--solid");
  await page.waitForSelector(".live-log .sheet", { timeout: 8000 });
});
await check("live log balances 24.00 and shows driving hours", async () => {
  const txt = await page.textContent(".live-log .sheet");
  if (!/24\.00|24\.0/.test(txt)) throw new Error("checksum missing");
  if (!/driving|hours/i.test(txt)) throw new Error("hours summary missing");
});

await check("plan a trip still renders a route", async () => {
  await page.click('.rail-link:has-text("plan a trip")');
  await page.waitForSelector(".trip-form", { timeout: 5000 });
  await page.fill('input[placeholder="Dallas, TX"]', "Dallas, TX");
  if (await page.locator('input[placeholder="Memphis, TN"]').count())
    await page.fill('input[placeholder="Memphis, TN"]', "Ft Worth, TX");
  await page.fill('input[placeholder="Chicago, IL"]', "Austin, TX");
  await page.fill('input[type="number"]', "20");
  await page.click('.trip-form button[type="submit"]');
  await page.waitForSelector(".route-summary", { timeout: 60000 });
});

/* ---------- admin console ---------- */
await check("admin login lands on /dispatch, admin link present", async () => {
  await page.evaluate(() => localStorage.clear());
  await login("admin", "http://localhost:5173/dispatch");
  await page.waitForSelector('a.topbar-link:text("Admin")', { timeout: 8000 });
});

await check("admin console drivers table with duty hours", async () => {
  await page.click('a.topbar-link:text("Admin")');
  await page.waitForSelector(".admin-table tbody tr", { timeout: 8000 });
  const body = await page.textContent("body");
  if (!/cycle/i.test(body)) throw new Error("cycle column missing");
});

await check("admin adds a vehicle", async () => {
  await page.click('.rail-link:text("Vehicles")');
  await page.waitForSelector(".admin-table");
  const before = await page.locator(".admin-table tbody tr").count();
  await page.click('button:has-text("add vehicle")');
  await page.fill('input[class="input-mini"]', `ADM-${Date.now().toString().slice(-5)}`);
  await page.click('button:has-text("save vehicle")');
  await page.waitForSelector(".toast", { timeout: 8000 });
  const after = await page.locator(".admin-table tbody tr").count();
  if (after !== before + 1) throw new Error(`rows ${before} -> ${after}`);
});

await check("admin edits a driver", async () => {
  await page.click('.rail-link:text("Drivers")');
  const row = page.locator('tr:has-text("danton")');
  if (await row.count() !== 1) throw new Error("danton row missing");
  await row.locator('button:has-text("edit")').click();
  await page.waitForSelector('button:has-text("save driver")', { timeout: 5000 });
  await page.locator('button:has-text("save driver")').click();
  await page.waitForSelector(".toast", { timeout: 8000 });
});

/* ---------- dispatcher fleet tabs ---------- */
await check("dispatcher has fleet tabs, no admin create buttons", async () => {
  await page.evaluate(() => localStorage.clear());
  await login("dispatch", "http://localhost:5173/dispatch");
  await page.waitForSelector('button.chip:text("Drivers")', { timeout: 8000 });
  await page.click('button.chip:text("Vehicles")');
  await page.waitForSelector(".admin-table");
  if (await page.locator('button:has-text("add vehicle")').count())
    throw new Error("dispatcher saw add-vehicle button");
});

/* ---------- auditor safety ---------- */
await check("auditor lands on /safety with KPIs", async () => {
  await page.evaluate(() => localStorage.clear());
  await login("auditor", "http://localhost:5173/safety");
  await page.waitForSelector(".kpi-strip", { timeout: 8000 });
  const body = await page.textContent("body");
  if (!/packet|pdf|download|compliance/i.test(body)) throw new Error("export control missing");
});

await browser.close();
console.log(results.join("\n"));
console.log(`JS errors: ${errors.length ? errors.join(" | ") : "none"}`);
console.log(`summary: ${pass} passed, ${fail} failed`);
if (fail > 0 || errors.length) process.exit(1);