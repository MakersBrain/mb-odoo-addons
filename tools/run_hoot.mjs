#!/usr/bin/env node

// Browser-only Hoot gate.  It intentionally uses the Chrome DevTools Protocol
// and Node built-ins so the pinned Playwright image supplies the browser while
// no floating npm dependency is installed at runtime.

import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const CHROMIUM_EXECUTABLE =
    process.env.CHROMIUM_EXECUTABLE ||
    "/ms-playwright/chromium-1187/chrome-linux/chrome";
const BASE_URL = process.env.HOOT_BASE_URL || "http://127.0.0.1:8169";
const DATABASE = process.env.HOOT_DATABASE || "mb_scratch";
const LOGIN = process.env.HOOT_LOGIN || "admin";
const PASSWORD = process.env.HOOT_PASSWORD || "admin";
const OUTPUT_DIR = process.env.HOOT_OUTPUT_DIR || "/tmp/mb-odoo-hoot-artifacts";
const DEBUG_PORT = Number(process.env.HOOT_DEBUG_PORT || 9223);
const TIMEOUT_MS = Number(process.env.HOOT_TIMEOUT_MS || 120_000);
const EXPECTED_SUITES = new Map([
    ["@mb_inventory_capture", 3],
    ["@mb_label", 18],
    ["@mb_label_pos", 10],
]);
const EXPECTED_TOTAL = [...EXPECTED_SUITES.values()].reduce((sum, count) => sum + count, 0);
const REPOSITORY_FILTER = "/^@(mb_inventory_capture|mb_label|mb_label_pos)(?:\\/|$)/";

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForJson(url, timeout = 30_000) {
    const deadline = Date.now() + timeout;
    let lastError;
    while (Date.now() < deadline) {
        try {
            const response = await fetch(url);
            if (response.ok) return response.json();
            lastError = new Error(`${url} returned HTTP ${response.status}`);
        } catch (error) {
            lastError = error;
        }
        await sleep(250);
    }
    throw new Error(`Timed out waiting for ${url}: ${lastError}`);
}

class CDP {
    constructor(webSocketUrl) {
        this.nextId = 0;
        this.pending = new Map();
        this.listeners = new Map();
        this.ready = new Promise((resolve, reject) => {
            this.socket = new WebSocket(webSocketUrl);
            this.socket.addEventListener("open", resolve, { once: true });
            this.socket.addEventListener("error", reject, { once: true });
            this.socket.addEventListener("message", (event) => this.onMessage(event));
        });
    }

    onMessage(event) {
        const message = JSON.parse(event.data);
        if (message.id && this.pending.has(message.id)) {
            const { resolve, reject } = this.pending.get(message.id);
            this.pending.delete(message.id);
            if (message.error) reject(new Error(JSON.stringify(message.error)));
            else resolve(message.result || {});
            return;
        }
        for (const listener of this.listeners.get(message.method) || []) {
            listener(message.params || {});
        }
    }

    on(method, listener) {
        if (!this.listeners.has(method)) this.listeners.set(method, []);
        this.listeners.get(method).push(listener);
    }

    async call(method, params = {}) {
        await this.ready;
        const id = ++this.nextId;
        const result = new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject });
        });
        this.socket.send(JSON.stringify({ id, method, params }));
        return result;
    }

    async evaluate(expression, awaitPromise = false) {
        const response = await this.call("Runtime.evaluate", {
            expression,
            awaitPromise,
            returnByValue: true,
        });
        if (response.exceptionDetails) {
            throw new Error(response.exceptionDetails.exception?.description || "browser evaluation failed");
        }
        return response.result?.value;
    }

    close() {
        this.socket?.close();
    }
}

async function waitFor(cdp, expression, description) {
    const deadline = Date.now() + TIMEOUT_MS;
    while (Date.now() < deadline) {
        const value = await cdp.evaluate(expression);
        if (value) return value;
        await sleep(250);
    }
    throw new Error(`Timed out waiting for ${description}`);
}

function parseSuiteCount(title) {
    const match = title.match(/\n- (\d+) tests?\n/);
    return match ? Number(match[1]) : 0;
}

await mkdir(OUTPUT_DIR, { recursive: true });
const profile = await mkdtemp(path.join(os.tmpdir(), "mb-hoot-chromium-"));
const chromiumLogPath = path.join(OUTPUT_DIR, "chromium.log");
const browserConsole = [];
let browser;
let cdp;
let chromiumLog = "";
let result = { ok: false, expectedTotal: EXPECTED_TOTAL };

try {
    browser = spawn(
        CHROMIUM_EXECUTABLE,
        [
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--remote-allow-origins=*",
            `--remote-debugging-port=${DEBUG_PORT}`,
            `--user-data-dir=${profile}`,
            "about:blank",
        ],
        { stdio: ["ignore", "ignore", "pipe"] },
    );
    browser.stderr.on("data", (chunk) => {
        chromiumLog += chunk.toString();
    });

    const targets = await waitForJson(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
    const page = targets.find((target) => target.type === "page");
    if (!page) throw new Error("Chromium exposed no debuggable page target");
    cdp = new CDP(page.webSocketDebuggerUrl);
    await cdp.call("Page.enable");
    await cdp.call("Runtime.enable");
    await cdp.call("Log.enable");
    cdp.on("Runtime.consoleAPICalled", ({ type, args }) => {
        if (type === "error") {
            browserConsole.push({
                type,
                values: args.map((argument) => argument.value ?? argument.description ?? ""),
            });
        }
    });
    cdp.on("Runtime.exceptionThrown", ({ exceptionDetails }) => {
        browserConsole.push({
            type: "exception",
            values: [exceptionDetails.exception?.description || exceptionDetails.text],
        });
    });
    cdp.on("Log.entryAdded", ({ entry }) => {
        if (entry.level === "error") browserConsole.push({ type: "log", values: [entry.text] });
    });

    await cdp.call("Page.navigate", { url: `${BASE_URL}/web/login` });
    await waitFor(cdp, "document.readyState === 'complete'", "Odoo login page");
    const uid = await cdp.evaluate(
        `fetch('/web/session/authenticate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {
                db: ${JSON.stringify(DATABASE)},
                login: ${JSON.stringify(LOGIN)},
                password: ${JSON.stringify(PASSWORD)}
            }, id: 1})
        }).then(response => response.json()).then(payload => payload.result?.uid || 0)`,
        true,
    );
    if (!uid) throw new Error(`Authentication failed for ${LOGIN} on ${DATABASE}`);

    await cdp.call("Page.navigate", {
        url: `${BASE_URL}/web/tests?debug=assets&manual=true`,
    });
    const discovered = await waitFor(
        cdp,
        `(() => {
            const root = document.querySelector('hoot-container')?.shadowRoot;
            if (!root) return null;
            const wanted = ${JSON.stringify([...EXPECTED_SUITES.keys()])};
            const suites = [...root.querySelectorAll('.hoot-sidebar-suite')]
                .filter(button => wanted.some(name => button.title.startsWith(name + '\\n')))
                .map(button => ({
                    title: button.title,
                    href: button.querySelector('[title="Run this suite only"]')?.href || ''
                }));
            return suites.length === wanted.length ? suites : null;
        })()`,
        "repository Hoot suite discovery",
    );

    const discoveredCounts = {};
    for (const suite of discovered) {
        const name = suite.title.split("\n", 1)[0];
        const count = parseSuiteCount(suite.title);
        discoveredCounts[name] = count;
        if (count !== EXPECTED_SUITES.get(name)) {
            throw new Error(
                `${name} discovered ${count} tests; expected ${EXPECTED_SUITES.get(name)}`,
            );
        }
    }
    if (EXPECTED_TOTAL <= 0) {
        throw new Error("Hoot discovery returned zero repository tests");
    }

    browserConsole.length = 0;
    const testUrl = new URL(`${BASE_URL}/web/tests`);
    testUrl.searchParams.set("debug", "assets");
    testUrl.searchParams.set("showdetail", "failed");
    testUrl.searchParams.set("filter", REPOSITORY_FILTER);
    await cdp.call("Page.navigate", { url: testUrl.toString() });
    const report = await waitFor(
        cdp,
        `(() => {
            const root = document.querySelector('hoot-container')?.shadowRoot;
            const status = root?.querySelector('.HootStatusPanel');
            if (!status?.textContent.includes('tests completed')) return null;
            const wanted = ${JSON.stringify([...EXPECTED_SUITES.keys()])};
            const suites = [...root.querySelectorAll('.hoot-sidebar-suite')]
                .filter(button => wanted.some(name => button.title.startsWith(name + '\\n')))
                .map(button => ({
                    title: button.title,
                    failed: button.querySelector('span.truncate')?.classList.contains('text-rose') || false
                }));
            const failures = [...root.querySelectorAll('.HootTestResult')]
                .filter(node => node.querySelector('.bg-rose'))
                .map(node => node.textContent.trim());
            return {status: status.textContent.trim(), suites, failures};
        })()`,
        "Hoot completion",
    );

    const completedMatch = report.status.match(/(\d+) tests completed/);
    const completed = completedMatch ? Number(completedMatch[1]) : 0;
    const failedSuites = report.suites.filter((suite) => suite.failed);
    result = {
        ok:
            completed === EXPECTED_TOTAL &&
            report.suites.length === EXPECTED_SUITES.size &&
            !failedSuites.length &&
            !report.failures.length &&
            !browserConsole.length,
        expectedTotal: EXPECTED_TOTAL,
        completed,
        discoveredCounts,
        status: report.status,
        failedSuites,
        failures: report.failures,
        browserConsole,
        testUrl: testUrl.toString(),
    };
    if (!result.ok) throw new Error("Hoot gate reported failures; inspect result.json");
    await writeFile(chromiumLogPath, chromiumLog);
} catch (error) {
    result.error = error.stack || String(error);
    if (cdp) {
        try {
            const screenshot = await cdp.call("Page.captureScreenshot", { format: "png" });
            await writeFile(path.join(OUTPUT_DIR, "failure.png"), screenshot.data, "base64");
        } catch (screenshotError) {
            result.screenshotError = String(screenshotError);
        }
    }
} finally {
    await writeFile(chromiumLogPath, chromiumLog);
    await writeFile(path.join(OUTPUT_DIR, "browser-console.json"), JSON.stringify(browserConsole, null, 2));
    await writeFile(path.join(OUTPUT_DIR, "result.json"), JSON.stringify(result, null, 2));
    cdp?.close();
    if (browser && browser.exitCode === null) {
        browser.kill("SIGTERM");
        await Promise.race([once(browser, "exit"), sleep(2_000)]);
    }
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}

console.log(JSON.stringify(result));
if (!result.ok) process.exitCode = 1;
