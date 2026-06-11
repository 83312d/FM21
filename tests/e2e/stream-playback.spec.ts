/**
 * FM21 stream playback e2e — moscow + spb mounts (U-TDD-4).
 * Asserts Play connects without reconnect loop status text.
 */

import { execFileSync } from "node:child_process";
import { describe, expect, it, beforeAll, afterAll } from "vitest";

const GATEWAY_URL =
  process.env.GATEWAY_URL ?? process.env.FM21_GATEWAY_URL ?? "http://gateway";
const SESSION = "fm21-stream-playback";

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

function statusText(): string {
  return evalJs<string>(
    "(() => { const el = document.querySelector('[data-testid=\"status\"]'); return el ? (el.textContent || '').trim() : ''; })()",
  );
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

describe("FM21 stream playback", () => {
  it("moscow — Play connects without reconnect status", () => {
    ab("open", `${GATEWAY_URL}/?city=moscow`);
    ab("wait", "[data-testid='play-btn']");
    playAndWaitUnpaused();

    const status = statusText();
    expect(status).not.toMatch(/Повтор подключения/);
    expect(status).toBe("");

    const src = evalJs<string>("document.querySelector('[data-testid=\"stream\"]')?.src ?? ''");
    expect(src).toContain("/moscow");
  });

  it("spb — Play connects without reconnect status", () => {
    ab("open", `${GATEWAY_URL}/?city=spb`);
    ab("wait", "[data-testid='play-btn']");
    playAndWaitUnpaused();

    const status = statusText();
    expect(status).not.toMatch(/Повтор подключения/);
    expect(status).toBe("");

    const src = evalJs<string>("document.querySelector('[data-testid=\"stream\"]')?.src ?? ''");
    expect(src).toContain("/spb");
  });
});
