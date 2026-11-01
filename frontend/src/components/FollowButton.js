// src/components/FollowButton.js
// "Notify me" on a TV show: new episodes show up in the navbar bell and by email.
import React, { useEffect, useRef, useState } from "react";
import { fetchFollow, setFollow } from "../api/recoApi";
import { useTranslation } from "react-i18next";
import { Button } from "../design";
import { BellIcon } from "../design/icons";

export default function FollowButton({ titleId, variant = "glass" }) {
  const { t } = useTranslation("catalog");
  const profileId = localStorage.getItem("activeProfileId");
  const [following, setFollowing] = useState(false);
  const touched = useRef(false); // clicked before the server answered: its answer is stale

  useEffect(() => {
    if (!titleId || !profileId) return;
    let alive = true;
    touched.current = false;
    fetchFollow({ profileId, titleId })
      .then((f) => alive && !touched.current && setFollowing(f))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [titleId, profileId]);

  if (!profileId) return null;

  const toggle = () => {
    const next = !following;
    touched.current = true;
    setFollowing(next); // instant feedback, undone if the server refuses
    setFollow({ profileId, titleId, following: next }).catch(() => setFollowing(!next));
  };

  return (
    <Button
      variant={variant}
      icon={<BellIcon />}
      pressed={following}
      label={following ? t("follow.following") : t("follow.notify")}
      title={following ? t("follow.stopHint") : t("follow.notifyHint")}
      onClick={toggle}
    />
  );
}
