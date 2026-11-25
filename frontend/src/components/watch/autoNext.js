// Next episode by the app, for every source (ROADMAP 9.3). Pure helpers, tested in autoNext.test.js.
// The watch page shows a "Next episode in 10" card when the player says the episode ended, or in
// its last 30 s when the player sends times; then it loads S/E+1 on the same source.

export const NEXT_COUNTDOWN_S = 10; // "Next episode in 10"
export const NEXT_CREDITS_S = 30; // the card shows this long before the end (players that send times)
export const NEXT_MIN_DURATION_S = 300; // shorter = not an episode (a trailer, a wrong duration)
export const STILL_WATCHING_AFTER = 3; // episodes started by themselves without a key press: "Still watching?"

/**
 * The episode after `season` / `episode` that is already out: the rest of this season, then the
 * first aired episode of a later season. `seasons`: the title's seasons ({ season_number,
 * episodes: [{ episode_number, air_date, name, still_path }] }). Returns
 * { season, episode, name, still } or null (the show's last episode, or nothing aired after it).
 */
export function findNextEpisode(seasons, season, episode, today = new Date().toISOString().slice(0, 10)) {
  if (!Array.isArray(seasons)) return null;
  const aired = (s) =>
    (s?.episodes || [])
      .filter((ep) => !ep.air_date || ep.air_date <= today)
      .sort((a, b) => Number(a.episode_number) - Number(b.episode_number));
  const pack = (s, ep) => ({
    season: Number(s.season_number),
    episode: Number(ep.episode_number),
    name: ep.name || "",
    still: ep.still_path || "",
  });

  const sorted = [...seasons].sort((a, b) => Number(a.season_number) - Number(b.season_number));
  const current = sorted.find((s) => Number(s.season_number) === Number(season));
  const later = aired(current).find((ep) => Number(ep.episode_number) > Number(episode));
  if (later) return pack(current, later);
  for (const s of sorted) {
    // season 0 ("Specials") never comes after a real season
    if (Number(s.season_number) > Number(season) && Number(s.season_number) > 0) {
      const first = aired(s)[0];
      if (first) return pack(s, first);
    }
  }
  return null;
}

/** A player event ({ position, duration, ended }) says the episode is at its end: show the card */
export function isEpisodeEnding(ev) {
  if (!ev) return false;
  if (ev.ended) return true;
  const { position, duration } = ev;
  if (!Number.isFinite(position) || !Number.isFinite(duration) || duration < NEXT_MIN_DURATION_S) return false;
  return position > 0 && duration - position <= NEXT_CREDITS_S;
}

/** What the card at an episode's end does: "countdown" (starts by itself), "offer" (waits), "still" (Still watching?), "end" (show over) */
export function upNextMode({ next, autoplay, autoStarts }) {
  if (!next) return "end";
  if (!autoplay) return "offer";
  if (autoStarts >= STILL_WATCHING_AFTER) return "still";
  return "countdown";
}
