import { describe, expect, it } from "vitest";
import { isPlayerMessage, nextSource, orderSources } from "./sourceOrder";

const P = (key, down = false) => ({ key, down });
const providers = [P("a"), P("b"), P("c"), P("d", true)];

describe("orderSources", () => {
  it("keeps the server's order without any memory", () => {
    expect(orderSources(providers)).toEqual(["a", "b", "c", "d"]);
  });

  it("starts on what worked: this title, then the one picked here, then this profile", () => {
    expect(orderSources(providers, { title: "c", saved: "b", profile: "d" })).toEqual(["c", "b", "d", "a"]);
    expect(orderSources(providers, { profile: "b" })).toEqual(["b", "a", "c", "d"]);
  });

  it("tries the sources that failed on this title last, before the unreachable ones", () => {
    expect(orderSources(providers, { failed: ["a"] })).toEqual(["b", "c", "a", "d"]);
    expect(orderSources(providers, { saved: "a", failed: ["a"] })).toEqual(["b", "c", "a", "d"]);
  });

  it("ignores keys that aren't sources of this title (disabled, no TV link)", () => {
    expect(orderSources([P("a"), P("b")], { title: "zz", failed: ["yy"] })).toEqual(["a", "b"]);
    expect(orderSources([], { title: "a" })).toEqual([]);
  });
});

describe("nextSource", () => {
  it("goes through the whole list once, then gives up", () => {
    const order = ["a", "b", "c"];
    const tried = new Set(["a"]);
    expect(nextSource(order, "a", tried)).toBe("b");
    tried.add("b");
    expect(nextSource(order, "b", tried)).toBe("c");
    tried.add("c");
    expect(nextSource(order, "c", tried)).toBeNull();
  });

  it("comes back to an earlier source the viewer skipped", () => {
    // the viewer jumped straight to c: a and b were never tried
    expect(nextSource(["a", "b", "c"], "c", new Set(["c"]))).toBe("a");
  });
});

describe("isPlayerMessage", () => {
  it("knows the players' messages, also the ones that don't mean playback", () => {
    expect(isPlayerMessage({ type: "cinesrc:ready" })).toBe(true);
    expect(isPlayerMessage("vidcore:pause")).toBe(true);
    expect(isPlayerMessage(JSON.stringify({ type: "PLAYER_EVENT", data: {} }))).toBe(true);
  });

  it("ignores everything else (ads, analytics, other frames)", () => {
    expect(isPlayerMessage({ type: "ad:click" })).toBe(false);
    expect(isPlayerMessage("hello")).toBe(false);
    expect(isPlayerMessage(null)).toBe(false);
    expect(isPlayerMessage({ foo: 1 })).toBe(false);
  });
});
