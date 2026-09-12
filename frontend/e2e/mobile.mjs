import { chromium } from "/home/morpheus/Projects/spotter/venv/lib/python3.11/site-packages/playwright/driver/package/index.mjs";

const base = process.env.BASE_URL || "http://localhost:5173";
const results = [];
let pass = 0, fail = 0;

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

function noHScroll() {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
}

const browser = await chromium.launch({
  executablePath: "/home/morpheus/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
});
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
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

await check("mobile: hamburger opens the drawer", async () => {
  await login("danton", "http://localhost:5173/$");
  await page.waitForSelector(".menu-btn", { timeout: 8000 });
  await page.click(".menu-btn");
  await page.waitForSelector(".rail.rail-open", { timeout: 5000 });
  await page.click(".menu-btn");
  await page.waitForSelector(".rail:not(.rail-open)", { timeout: 5000 });
});

await check("mobile: driver cab, no horizontal scroll", async () => {
  await page.click(".menu-btn");
  await page.click('.rail-link:has-text("plan a trip")');
  await page.waitForSelector(".trip-form", { timeout: 5000 });
  if (!(await noHScroll())) throw new Error("driver cab overflows horizontally");
});

await check("mobile: admin vehicles table renders as stacked cards", async () => {
  await page.evaluate(() => localStorage.clear());
  await login("admin", "http://localhost:5173/dispatch");
  await page.click('a.topbar-link:text("admin")');
  await page.waitForSelector(".admin-table tbody tr", { timeout: 8000 });
  await page.click(".menu-btn");
  await page.click('.rail-link:text("vehicles")');
  await page.waitForSelector(".admin-table");
  const sample = await page.locator('.admin-table tbody tr td[data-label]').first().count();
  if (!sample) throw new Error("no data-label cells for mobile cards");
  const labelShown = await page.locator(".admin-table tbody tr").first().evaluate((tr) => {
    const td = tr.querySelector("td[data-label]");
    return getComputedStyle(td, "::before").content !== "none";
  });
  if (!labelShown) throw new Error("data-label ::before not rendering");
  if (!(await noHScroll())) throw new Error("admin table overflows horizontally");
});

await check("mobile: dispatcher fleet chips work", async () => {
  await page.evaluate(() => localStorage.clear());
  await login("dispatch", "http://localhost:5173/dispatch");
  await page.waitForSelector('.chip:text("drivers")', { timeout: 8000 });
  await page.click('.chip:text("vehicles")');
  await page.waitForSelector(".admin-table");
  if (await page.locator('button:has-text("add vehicle")').count())
    throw new Error("dispatcher saw add-vehicle button");
  if (!(await noHScroll())) throw new Error("dispatch board overflows horizontally");
});

await check("mobile: auditor safety KPIs fit", async () => {
  await page.evaluate(() => localStorage.clear());
  await login("auditor", "http://localhost:5173/safety");
  await page.waitForSelector(".kpi-strip", { timeout: 8000 });
  if (await page.locator(".kpi-card").count() < 3) throw new Error("kpis missing");
  if (!(await noHScroll())) throw new Error("safety view overflows horizontally");
});

await check("mobile: login page has demo chips and no scroll", async () => {
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${base}/login`);
  await page.waitForSelector(".demo-chips .chip", { timeout: 8000 });
  await page.click('.demo-chips .chip:text("driver")');
  const val = await page.inputValue('input[autocomplete="username"]');
  if (val !== "danton") throw new Error("demo chip did not fill username");
  if (!(await noHScroll())) throw new Error("login overflows horizontally");
});

await browser.close();
console.log(results.join("\n"));
console.log(`JS errors: ${errors.length ? errors.join(" | ") : "none"}`);
console.log(`summary: ${pass} passed, ${fail} failed`);
if (fail > 0 || errors.length) process.exit(1);