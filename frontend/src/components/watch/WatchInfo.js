// src/components/watch/WatchInfo.js
// Under the player: what's playing (episode name + synopsis, or the movie's description) and, for
// shows, the episodes of the season (season chips + a scrolling row, the one playing marked;
// choosing one plays it). Filled the empty space under the sources on phones.
import React, { useMemo, useState } from 'react';
import { Chip, SectionTitle } from '../../design';
import { PlayIcon } from '../../design/icons';
import { tmdbImage, IMG } from '../../utils/tmdbImage';
import './watch-info.css';

const stillUrl = (path) => (path ? `https://image.tmdb.org/t/p/w300/${String(path).replace(/^\//, '')}` : '');
const today = () => new Date().toISOString().slice(0, 10);

export default function WatchInfo({ title, isTV, seasonNumber, episodeNumber, onPlayEpisode }) {
  const seasons = useMemo(
    () =>
      (Array.isArray(title?.seasons) ? [...title.seasons] : [])
        .filter((s) => (s.episodes || []).length)
        .sort((a, b) => (a.season_number || 999) - (b.season_number || 999)),
    [title]
  );
  const [shownSeason, setShownSeason] = useState(Number(seasonNumber) || seasons[0]?.season_number);
  const season = seasons.find((s) => Number(s.season_number) === Number(shownSeason)) || seasons[0];
  const episodes = useMemo(
    () => [...(season?.episodes || [])].sort((a, b) => a.episode_number - b.episode_number),
    [season]
  );
  const playing = isTV
    ? seasons
        .find((s) => Number(s.season_number) === Number(seasonNumber))
        ?.episodes?.find((e) => Number(e.episode_number) === Number(episodeNumber))
    : null;

  const heading = isTV
    ? `S${seasonNumber} · E${episodeNumber}${playing?.name ? ` · ${playing.name}` : ''}`
    : title?.title;
  const text = (isTV ? playing?.overview : '') || title?.description || '';
  const art = title?.landscape_image || title?.poster || '';

  return (
    <div className="watch-info">
      <section className="watch-info__about" aria-label="About">
        <h2 className="watch-info__title">{heading}</h2>
        {text ? <p className="watch-info__text">{text}</p> : null}
      </section>

      {isTV && seasons.length ? (
        <section className="watch-info__episodes" aria-labelledby="watch-episodes-title">
          <div className="watch-info__head">
            <SectionTitle as="h2" id="watch-episodes-title">
              Episodes
            </SectionTitle>
            {seasons.length > 1 ? (
              <div className="ui-scroller watch-info__seasons" role="group" aria-label="Season">
                {seasons.map((s) => (
                  <Chip
                    key={s.season_number}
                    selected={Number(s.season_number) === Number(season?.season_number)}
                    onClick={() => setShownSeason(s.season_number)}
                  >
                    {s.season_number === 0 ? 'Specials' : `Season ${s.season_number}`}
                  </Chip>
                ))}
              </div>
            ) : null}
          </div>
          <ul className="ui-scroller watch-info__row" aria-label={`Season ${season?.season_number} episodes`}>
            {episodes.map((ep) => {
              const isPlaying =
                Number(season?.season_number) === Number(seasonNumber) && Number(ep.episode_number) === Number(episodeNumber);
              const notAired = ep.air_date && ep.air_date > today();
              const img = stillUrl(ep.still_path) || (art ? tmdbImage(art, IMG.backdropCard) : '');
              return (
                <li key={ep.id || ep.episode_number}>
                  <button
                    type="button"
                    className={`watch-ep${isPlaying ? ' is-active' : ''}`}
                    aria-current={isPlaying ? 'true' : undefined}
                    disabled={notAired}
                    onClick={() => !isPlaying && onPlayEpisode(season.season_number, ep.episode_number)}
                    aria-label={`Episode ${ep.episode_number}${ep.name ? `: ${ep.name}` : ''}${isPlaying ? ' (playing)' : ''}${notAired ? ' (coming soon)' : ''}`}
                  >
                    <span className={`watch-ep__still${ep.still_path ? '' : ' is-fallback'}`} style={img ? { backgroundImage: `url(${img})` } : undefined}>
                      {!ep.still_path ? <span className="watch-ep__num">{ep.episode_number}</span> : null}
                      {isPlaying ? (
                        <span className="watch-ep__playing">Playing</span>
                      ) : notAired ? (
                        <span className="watch-ep__playing watch-ep__playing--soon">Soon</span>
                      ) : (
                        <span className="watch-ep__play" aria-hidden="true">
                          <PlayIcon />
                        </span>
                      )}
                    </span>
                    <span className="watch-ep__title">
                      {ep.episode_number}. {ep.name || `Episode ${ep.episode_number}`}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
