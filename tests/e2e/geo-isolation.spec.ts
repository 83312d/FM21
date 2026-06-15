/**
 * FM21 listener e2e — agent-browser (U7).
 * Covers AE4, AE-CITY-SWITCH, AE6, AE-NOW-PLAYING, mount isolation.
 */

import { execFileSync } from "node:child_process";
import { describe, expect, it, beforeAll, afterAll } from "vitest";

const GATEWAY_URL =
  process.env.GATEWAY_URL ?? process.env.FM21_GATEWAY_URL ?? "http://gateway";
const SESSION = "fm21-e2e";

function ab(...args: string[]): string {
  return execFileSync("agent-browser", ["--session", SESSION, ...args], {
    encoding: "utf-8",
    env: {
      ...process.env,
      AGENT_BROWSER_HEADED: "0",
    },
    stdio: ["pipe", "pipe", "pipe"],
  }).trim();
}

function evalJs<T>(script: string): T {
  const output = execFileSync(
    "agent-browser",
    ["--session", SESSION, "--json", "eval", script],
    {
      encoding: "utf-8",
      env: { ...process.env, AGENT_BROWSER_HEADED: "0" },
    },
  ).trim();
  try {
    const parsed = JSON.parse(output) as {
      data?: { result?: T };
      result?: T;
      value?: T;
    };
    return (parsed.data?.result ?? parsed.result ?? parsed.value ?? parsed) as T;
  } catch {
    return output as T;
  }
}

function grantGeolocation(lat: number, lon: number) {
  ab("set", "geo", String(lat), String(lon));
}

function denyGeolocation() {
  // No dedicated deny flag in agent-browser; rely on URL/localStorage chain in AE4.
  ab("set", "geo", "0", "0");
}

beforeAll(() => {
  ab("close");
});

afterAll(() => {
  ab("close");
});

describe("FM21 web player", () => {
  it("AE4 — badge and Play without blocking modal (geo denied)", () => {
    denyGeolocation();
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");

    const snapshot = ab("snapshot", "-i", "-s", "#fm21-player");
    expect(snapshot).toMatch(/Play|Воспроизвести/i);
    expect(snapshot).not.toMatch(/modal/i);

    const cityValue = evalJs<string>(
      "document.querySelector('[data-testid=\"city-select\"]')?.value",
    );
    expect(cityValue).toBe("moscow");

    const title = evalJs<string>("document.querySelector('[data-testid=\"now-title\"]')?.textContent");
    expect(title?.length).toBeGreaterThan(0);
  });

  it("happy path — Play connects to moscow mount", () => {
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");
    ab("click", "[data-testid='play-btn']");
    ab("wait", "--fn", "!document.querySelector('[data-testid=\"stream\"]').paused", "15000");

    const src = evalJs<string>("document.querySelector('[data-testid=\"stream\"]')?.src");
    expect(src).toContain("/moscow");

    const status = evalJs<string>(
      "(() => { const el = document.querySelector('[data-testid=\"status\"]'); return el ? (el.textContent || '').trim() : ''; })()",
    );
    expect(status).not.toMatch(/Повтор подключения/);
    expect(status).toBe("");
  });

  it("AE-CITY-SWITCH — reconnect to spb within 2s", () => {
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");
    ab("click", "[data-testid='play-btn']");
    ab("wait", "--fn", "!document.querySelector('[data-testid=\"stream\"]').paused", "15000");

    const started = Date.now();
    evalJs(
      "(() => { const sel = document.querySelector('[data-testid=\"city-select\"]'); sel.value = 'spb'; sel.dispatchEvent(new Event('change', { bubbles: true })); })()",
    );
    ab("wait", "--fn", "document.querySelector('[data-testid=\"stream\"]').src.includes('/spb')", "5000");

    const elapsed = Date.now() - started;
    expect(elapsed).toBeLessThan(2000);

    const src = evalJs<string>("document.querySelector('[data-testid=\"stream\"]').src");
    expect(src).toContain("/spb");
  });

  it("geo isolation — moscow and spb mounts differ", () => {
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");
    const moscowSrc = evalJs<string>(
      "document.querySelector('[data-testid=\"stream\"]').getAttribute('src') || document.querySelector('[data-testid=\"stream\"]').src",
    );

    ab("open", `${GATEWAY_URL}/?city=spb`);
    ab("wait", "[data-testid='play-btn']");
    const spbSrc = evalJs<string>(
      "document.querySelector('[data-testid=\"stream\"]').getAttribute('src') || document.querySelector('[data-testid=\"stream\"]').src",
    );

    expect(moscowSrc).toContain("moscow");
    expect(spbSrc).toContain("spb");
    expect(moscowSrc).not.toEqual(spbSrc);
  });

  it("AE-NOW-PLAYING — metadata fields visible after Play", () => {
    ab("close");
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");
    ab("click", "[data-testid='play-btn']");
    ab("wait", "--fn", "!document.querySelector('[data-testid=\"stream\"]').paused", "15000");
    ab(
      "wait",
      "--fn",
      "(() => { const t = document.querySelector('[data-testid=\"content-type\"]')?.textContent?.trim(); return t && t !== '—'; })()",
      "30000",
    );

    const title = evalJs<string>("document.querySelector('[data-testid=\"now-title\"]')?.textContent?.trim()");
    const typeLabel = evalJs<string>(
      "document.querySelector('[data-testid=\"content-type\"]')?.textContent?.trim()",
    );

    expect(title).toBeTruthy();
    expect(typeLabel).toBeTruthy();
    expect(typeLabel).not.toBe("—");
  });

  it("AE6 — audio continues when tab hidden for 60s", () => {
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");
    ab("click", "[data-testid='play-btn']");
    ab("wait", "--fn", "!document.querySelector('[data-testid=\"stream\"]').paused", "15000");

    evalJs("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'));");
    ab("wait", "60000");

    const paused = evalJs<boolean>("document.querySelector('[data-testid=\"stream\"]').paused");
    expect(paused).toBe(false);
  }, 120000);
});
