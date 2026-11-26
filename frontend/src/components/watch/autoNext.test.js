import { describe, expect, it } from "vitest";
import { findNextEpisode, isEpisodeEnding, upNextMode, STILL_WATCHING_AFTER } from "./autoNext";

const show = [
  { season_number: 2, episodes: [{ episode_number: 2, air_date: "2009-02-01" }, { episode_number: 1, air_date: "2009-01-01", name: "Seven Thirty-Seven", still_path: "/s2e1.jpg" }] },
  { season_number: 0, episodes: [{ episode_number: 1, air_date: "2008-06-01" }] },
  { season_number: 1, episodes: [{ episode_number: 1, air_date: "2008-01-01" }, { episode_number: 2, air_date: "2008-01-08", name: "Cat's in the Bag" }] },
  { season_number: 3, episodes: [{ episode_number: 1, air_date: "2030-01-01" }] },
];

describe("findNextEpisode", () => {
  it("the next one in the same season, with its name", () => {
    expect(findNextEpisode(show, 1, 1, "2026-01-01")).toEqual({ season: 1, episode: 2, name: "Cat's in the Bag", still: "" });
  });
  it("season end: the next season's first episode, with its picture", () => {
    expect(findNextEpisode(show, 1, 2, "2026-01-01")).toEqual({ season: 2, episode: 1, name: "Seven Thirty-Seven", still: "/s2e1.jpg" });
  });
  it("show end, or only unaired episodes left: nothing", () => {
    expect(findNextEpisode(show, 2, 2, "2026-01-01")).toBeNull();
    expect(findNextEpisode(show, 2, 2, "2031-01-01")).toEqual({ season: 3, episode: 1, name: "", still: "" });
  });
  it("specials (season 0) are never next after a real season", () => {
    expect(findNextEpisode(show, 0, 1, "2026-01-01")).toMatchObject({ season: 1, episode: 1 });
  });
  it("no seasons: nothing", () => {
    expect(findNextEpisode(undefined, 1, 1)).toBeNull();
  });
});

describe("isEpisodeEnding", () => {
  it("the player's ended event", () => {
    expect(isEpisodeEnding({ ended: true })).toBe(true);
  });
  it("the last 30 s of an episode, from the player's times", () => {
    expect(isEpisodeEnding({ position: 2800, duration: 2820 })).toBe(true);
    expect(isEpisodeEnding({ position: 2700, duration: 2820 })).toBe(false);
  });
  it("not for something too short to be an episode, or without times", () => {
    expect(isEpisodeEnding({ position: 100, duration: 110 })).toBe(false);
    expect(isEpisodeEnding({ playing: true })).toBe(false);
    expect(isEpisodeEnding(null)).toBe(false);
  });
});

describe("upNextMode", () => {
  const next = { season: 1, episode: 2 };
  it("counts down when the setting is on", () => {
    expect(upNextMode({ next, autoplay: true, autoStarts: 0 })).toBe("countdown");
  });
  it("only offers when the setting is off", () => {
    expect(upNextMode({ next, autoplay: false, autoStarts: 0 })).toBe("offer");
  });
  it("asks Still watching? after 3 episodes started by themselves", () => {
    expect(upNextMode({ next, autoplay: true, autoStarts: STILL_WATCHING_AFTER - 1 })).toBe("countdown");
    expect(upNextMode({ next, autoplay: true, autoStarts: STILL_WATCHING_AFTER })).toBe("still");
  });
  it("show end", () => {
    expect(upNextMode({ next: null, autoplay: true, autoStarts: 0 })).toBe("end");
  });
});
