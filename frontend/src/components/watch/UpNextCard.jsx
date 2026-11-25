// The card over the player at an episode's end (ROADMAP 9.3), for every source:
//   countdown: "Next episode in 10", the next one's picture, Play now / Cancel (starts at 0);
//   offer:     the same without the countdown ("Play next episode automatically" is off);
//   still:     "Still watching?" after 3 episodes started by themselves (TV left on);
//   end:       the show's last episode: a few titles like it, "More like this".
// The remote: the card takes the focus on its first button; Left / Right between its buttons,
// OK, Back = Cancel (WatchPage's Back handler).
import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../design";
import { PlayIcon } from "../../design/icons";
import { tmdbImage } from "../../utils/tmdbImage";
import { NEXT_COUNTDOWN_S } from "./autoNext";
import "./up-next.css";

const stillUrl = (path) => (path ? `https://image.tmdb.org/t/p/w300/${String(path).replace(/^\//, "")}` : "");

const UpNextCard = React.forwardRef(function UpNextCard(
  { mode, next, seconds, showTitle, similar, onPlay, onCancel, onOpenTitle, onMoreLikeThis },
  ref
) {
  const { t } = useTranslation("watch");

  if (mode === "end") {
    const list = similar || [];
    return (
      <section ref={ref} className="up-next up-next--end" role="dialog" aria-label={t("upNext.endTitle", { show: showTitle })}>
        <h2 className="up-next__title">{t("upNext.endTitle", { show: showTitle })}</h2>
        {list.length ? (
          <>
            <p className="up-next__text">{t("upNext.moreLikeThis")}</p>
            <div className="up-next__similar">
              {list.map((item) => (
                <button key={item.id} type="button" className="up-next__similarItem" onClick={() => onOpenTitle(item)}>
                  {item.poster ? <img src={tmdbImage(item.poster, "w185")} alt="" loading="lazy" /> : <span className="up-next__similarBlank" />}
                  <span className="up-next__similarName">{item.title}</span>
                </button>
              ))}
            </div>
          </>
        ) : null}
        <div className="up-next__actions">
          {list.length ? null : (
            <Button variant="primary" size="sm" onClick={onMoreLikeThis}>
              {t("upNext.moreLikeThis")}
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={onCancel}>
            {t("upNext.close")}
          </Button>
        </div>
      </section>
    );
  }

  const still = mode === "still";
  const heading = still
    ? t("upNext.stillTitle")
    : mode === "countdown"
      ? t("upNext.in", { seconds: Math.max(0, seconds) })
      : t("nextEpisode");
  const episodeLine = [t("catalog:episodeShort", { season: next.season, episode: next.episode }), next.name].filter(Boolean).join(" · ");
  const picture = stillUrl(next.still);

  return (
    <section ref={ref} className="up-next" role="dialog" aria-label={heading}>
      {picture && !still ? <img className="up-next__still" src={picture} alt="" loading="lazy" /> : null}
      <div className="up-next__body">
        <h2 className="up-next__title" aria-live={mode === "countdown" ? "off" : "polite"}>
          {heading}
        </h2>
        <p className="up-next__text">{still ? t("upNext.stillText", { show: showTitle }) : episodeLine}</p>
        {mode === "countdown" ? (
          <div className="up-next__bar" aria-hidden="true">
            <span style={{ "--up-next-left": `${(Math.max(0, seconds) / NEXT_COUNTDOWN_S) * 100}%` }} />
          </div>
        ) : null}
        <div className="up-next__actions">
          <Button variant="primary" size="sm" icon={<PlayIcon />} onClick={onPlay}>
            {still ? t("upNext.continue") : t("upNext.playNow")}
          </Button>
          <Button variant="secondary" size="sm" onClick={onCancel}>
            {still ? t("upNext.stop") : t("upNext.cancel")}
          </Button>
        </div>
      </div>
    </section>
  );
});

export default UpNextCard;
