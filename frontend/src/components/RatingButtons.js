// src/components/RatingButtons.js
// 👍 / 👎 on a title for the active profile. Clicking the active thumb again clears it.
// Recommendations: like = strong interest, dislike = never recommended + similar titles go down.
import React, { useEffect, useState } from "react";
import { fetchRating, setRating } from "../api/recoApi";

export default function RatingButtons({ titleId, buttonClassName }) {
  const profileId = localStorage.getItem("activeProfileId");
  const [rating, setRatingState] = useState(null); // "like" | "dislike" | null

  useEffect(() => {
    if (!titleId || !profileId) return;
    let alive = true;
    fetchRating({ profileId, titleId })
      .then((r) => alive && setRatingState(r))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [titleId, profileId]);

  if (!profileId) return null;

  const choose = (value) => {
    const previous = rating;
    const next = rating === value ? null : value;
    setRatingState(next); // instant feedback, undone if the server refuses
    setRating({ profileId, titleId, rating: next }).catch(() => setRatingState(previous));
  };

  const style = (active) => ({
    opacity: rating && !active ? 0.55 : 1,
    outline: active ? "2px solid currentColor" : "none",
    outlineOffset: 2,
  });

  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button
        type="button"
        className={buttonClassName}
        style={style(rating === "like")}
        aria-pressed={rating === "like"}
        title={rating === "like" ? "Remove like" : "I like this"}
        onClick={() => choose("like")}
      >
        👍
      </button>
      <button
        type="button"
        className={buttonClassName}
        style={style(rating === "dislike")}
        aria-pressed={rating === "dislike"}
        title={rating === "dislike" ? "Remove dislike" : "Not for me: hide it and show less like it"}
        onClick={() => choose("dislike")}
      >
        👎
      </button>
    </div>
  );
}
