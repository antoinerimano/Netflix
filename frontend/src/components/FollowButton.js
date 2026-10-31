// src/components/FollowButton.js
// "Notify me" on a TV show: new episodes show up in the navbar bell and by email.
import React, { useEffect, useState } from "react";
import { fetchFollow, setFollow } from "../api/recoApi";
import { Button } from "../design";
import { BellIcon } from "../design/icons";

export default function FollowButton({ titleId, variant = "glass" }) {
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
      label={following ? "Following new episodes" : "Notify me of new episodes"}
      title={following ? "Stop new episode alerts" : "Get an alert (bell + email) when a new episode is out"}
      onClick={toggle}
    />
  );
}
