// src/components/FollowButton.js
// "Notify me" on a TV show: new episodes show up in the navbar bell and by email.
import React, { useEffect, useState } from "react";
import { fetchFollow, setFollow } from "../api/recoApi";
import { useTranslation } from "react-i18next";
import { Button } from "../design";
import { BellIcon } from "../design/icons";

export default function FollowButton({ titleId, variant = "glass" }) {
  const { t } = useTranslation("catalog");
  const profileId = localStorage.getItem("activeProfileId");
  const [following, setFollowing] = useState(false);

  useEffect(() => {
    if (!titleId || !profileId) return;
    let alive = true;
    fetchFollow({ profileId, titleId })
      .then((f) => alive && setFollowing(f))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [titleId, profileId]);

  if (!profileId) return null;

  const toggle = () => {
    const next = !following;
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
