// src/utils/tmdbImage.js
// TMDB images are stored at "original" size (posters ~750 KB, backdrops up to several MB).
// Always ask TMDB for the size actually displayed.

const SIZE_IN_URL = /\/t\/p\/(?:original|[wh]\d+)\//;

/** Same image at another TMDB size ("w342", "w1280", ...). Non-TMDB URLs are returned as they are. */
export function tmdbImage(url, size) {
  if (typeof url !== "string" || !url) return url || "";
  return SIZE_IN_URL.test(url) ? url.replace(SIZE_IN_URL, `/t/p/${size}/`) : url;
}

/** srcSet with width descriptors, e.g. tmdbSrcSet(poster, [185, 342, 500]); "" for non-TMDB URLs. */
export function tmdbSrcSet(url, widths) {
  if (typeof url !== "string" || !SIZE_IN_URL.test(url)) return undefined;
  return widths.map((w) => `${tmdbImage(url, `w${w}`)} ${w}w`).join(", ");
}

/** CSS background-image value at the given size (one size: image-set() isn't safe on older Safari). */
export function tmdbBackground(url, size) {
  return url ? `url("${tmdbImage(url, size)}")` : undefined;
}

// What each place displays
export const IMG = {
  backdropHero: "w1280", // full-width page backgrounds
  backdropCard: "w780", // home row cards
  blurredBackground: "w300", // blurred 18px at 30% opacity: details are invisible
  poster: "w342",
  posterLarge: "w500",
};
