import { describe, expect, it, vi } from "vitest";
import { reachable, whoIsAffected } from "./problemsApi";

describe("status page: down for me or everyone? (ROADMAP 9.8)", () => {
  it("a source's site answering at all is reachable; a network error or a hang is not", async () => {
    const ok = vi.fn().mockResolvedValue({ type: "opaque" });
    expect(await reachable("https://vidfast.pro/", { fetchImpl: ok })).toBe(true);
    expect(ok.mock.calls[0][0]).toBe("https://vidfast.pro/");
    expect(ok.mock.calls[0][1]).toMatchObject({ mode: "no-cors", credentials: "omit" });

    const blocked = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await reachable("https://vidfast.pro", { fetchImpl: blocked })).toBe(false);

    const hangs = (url, { signal }) =>
      new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("aborted"))));
    expect(await reachable("https://slow.example", { fetchImpl: hangs, timeoutMs: 20 })).toBe(false);
    expect(await reachable("", { fetchImpl: ok })).toBe(false);
  });

  it("who is affected: our checks first, then this browser's test", () => {
    const up = { key: "a", state: "up" };
    expect(whoIsAffected({ key: "a", state: "down" }, null)).toBe("everyone");
    expect(whoIsAffected(up, null)).toBe(null); // not tested from here yet
    expect(whoIsAffected(up, { a: false })).toBe("you");
    expect(whoIsAffected(up, { a: true })).toBe("ok");
    expect(whoIsAffected({ key: "a", state: "problems" }, { a: false })).toBe("you");
  });
});
