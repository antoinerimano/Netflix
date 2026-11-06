// src/components/RatingButtons.js
// 👍 / 👎 on a title for the active profile. Clicking the active thumb again clears it.
// Recommendations: like = strong interest, dislike = never recommended + similar titles go down.
import React, { useEffect, useRef, useState } from "react";
import { fetchRating, setRating } from "../api/recoApi";
import { useTranslation } from "react-i18next";
import { Button } from "../design";
import { ThumbUpIcon, ThumbDownIcon } from "../design/icons";

export default function RatingButtons({ titleId, variant = "glass" }) {
  const { t } = useTranslation("catalog");
  const profileId = localStorage.getItem("activeProfileId");
  const [rating, setRatingState] = useState(null); // "like" | "dislike" | null
  const touched = useRef(false); // clicked before the server answered: its answer is stale

  useEffect(() => {
    if (!titleId || !profileId) return;
    let alive = true;
    touched.current = false;
    fetchRating({ profileId, titleId })
      .then((r) => alive && !touched.current && setRatingState(r))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [titleId, profileId]);

  if (!profileId) return null;

  const choose = (value) => {
    const previous = rating;
    const next = rating === value ? null : value;
    touched.current = true;
    setRatingState(next); // instant feedback, undone if the server refuses
    setRating({ profileId, titleId, rating: next }).catch(() => setRatingState(previous));
  };

  return (
    <>
      <Button
        variant={variant}
        icon={<ThumbUpIcon />}
        pressed={rating === "like"}
        label={rating === "like" ? t("rate.liked") : t("rate.like")}
        onClick={() => choose("like")}
      />
      <Button
        variant={variant}
        icon={<ThumbDownIcon />}
        pressed={rating === "dislike"}
        label={t("rate.dislike")}
        title={t("rate.dislikeHint")}
        onClick={() => choose("dislike")}
      />
    </>
  );
}
