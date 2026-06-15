/**
 * FM21 full-product e2e smoke — U34 TZ §12 sign-off (local dev stack).
 * Health, geo API, player UX (volume, brand colors, sync-radio copy), mount playback.
 */

import { execFileSync } from "node:child_process";
import { describe, expect, it, beforeAll, afterAll } from "vitest";

const GATEWAY_URL =
  process.env.GATEWAY_URL ?? process.env.FM21_GATEWAY_URL ?? "http://gateway";
const SESSION = "fm21-full-product";

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

function curlJson(path: string): unknown {
  const url = `${GATEWAY_URL}${path}`;
  const out = execFileSync("curl", ["-sf", url], { encoding: "utf-8" });
  return JSON.parse(out);
}

function playAndWaitUnpaused() {
  ab("click", "[data-testid='play-btn']");
  ab("wait", "--fn", "!document.querySelector('[data-testid=\"stream\"]').paused", "15000");
}

beforeAll(() => {
  ab("close");
});

afterAll(() => {
  ab("close");
});

describe("FM21 full-product smoke", () => {
  it("health — GET /api/health returns status", () => {
    const body = curlJson("/api/health") as { status: string };
    expect(["ok", "degraded"]).toContain(body.status);
  });

  it("geo — GET /api/geo/detect returns city_tag without PII", () => {
    const body = curlJson("/api/geo/detect") as Record<string, string>;
    expect(body.city_tag).toBeTruthy();
    expect(body.city_name).toBeTruthy();
    expect(body.source).toBeTruthy();
    expect(body).not.toHaveProperty("ip");
    expect(body).not.toHaveProperty("lat");
    expect(body).not.toHaveProperty("lon");
  });

  it("web client — no auth gate; volume 0–100; brand colors", () => {
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");

    const snapshot = ab("snapshot", "-i", "-s", "#fm21-player");
    expect(snapshot).not.toMatch(/login|sign.?in|авториз/i);

    const volume = evalJs<{ min: string; max: string }>(
      "(() => { const el = document.querySelector('[data-testid=\"volume\"]'); return { min: el.min, max: el.max }; })()",
    );
    expect(volume.min).toBe("0");
    expect(volume.max).toBe("100");

    const colors = evalJs<{ accent: string; primary: string }>(
      "(() => { const s = getComputedStyle(document.documentElement); return { accent: s.getPropertyValue('--fm21-accent').trim(), primary: s.getPropertyValue('--fm21-primary').trim() }; })()",
    );
    expect(colors.accent.toUpperCase()).toBe("#44EB99");
    expect(colors.primary.toUpperCase()).toBe("#861BE3");
  });

  it("sync radio — live-edge tagline visible (AE5 UX)", () => {
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");

    const tagline = evalJs<string>(
      "document.querySelector('.player__tagline')?.textContent?.trim() ?? ''",
    );
    expect(tagline).toMatch(/прямому эфиру|live/i);
  });

  it("mounts — moscow and spb Play connect without reconnect loop", () => {
    for (const city of ["moscow", "spb"] as const) {
      ab("open", `${GATEWAY_URL}/?city=${city}`);
      ab("wait", "[data-testid='play-btn']");
      playAndWaitUnpaused();

      const status = evalJs<string>(
        "(() => { const el = document.querySelector('[data-testid=\"status\"]'); return el ? (el.textContent || '').trim() : ''; })()",
      );
      expect(status).not.toMatch(/Повтор подключения/);

      const src = evalJs<string>(
        "document.querySelector('[data-testid=\"stream\"]')?.src ?? ''",
      );
      expect(src).toContain(`/${city}`);
    }
  });
});
