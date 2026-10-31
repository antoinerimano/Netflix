// src/components/profiles/AvatarBuilder.js
// "Create your avatar": pick each part (background, pattern, face, skin, eyes, mouth, hair / hat,
// hair color, extras, top) with live previews of your own avatar, or "Surprise me". The result
// is a short code saved in Profile.avatar_url (design/avatarArt.js).
import React, { useEffect, useState } from 'react';
import { Button, Chip, Modal } from '../../design';
import { DiceIcon } from '../../design/icons';
import {
  AvatarArt, PARTS, BACKGROUNDS, SKINS, HAIR_COLORS, SHIRTS, encodeAvatar, parseAvatar, randomAvatar, isBuiltAvatar,
} from '../../design/avatarArt';

const SWATCHES = {
  bg: (i) => `linear-gradient(135deg, ${BACKGROUNDS[i][0]}, ${BACKGROUNDS[i][1]})`,
  sk: (i) => SKINS[i],
  hc: (i) => HAIR_COLORS[i],
  sh: (i) => SHIRTS[i],
};
// the order of the tabs (the saved code keeps PARTS' order): the fun parts first
const TAB_ORDER = ['hr', 'hc', 'ey', 'mo', 'ex', 'fc', 'sk', 'sh', 'bg', 'pt'];
const TABS = TAB_ORDER.map((k) => PARTS.find((p) => p.key === k));

const OPTION_NAMES = {
  pt: ['None', 'Dots', 'Stripes', 'Waves', 'Stars'],
  fc: ['Round', 'Square', 'Oval', 'Wide'],
  ey: ['Dots', 'Shiny', 'Happy', 'Wink', 'Sleepy', 'Stars', 'Shades', 'Big'],
  mo: ['Smile', 'Grin', 'Surprised', 'Neutral', 'Tongue', 'Smirk'],
  hr: ['None', 'Short', 'Spiky', 'Curly', 'Long', 'Bun', 'Mohawk', 'Cap', 'Beanie', 'Crown'],
  ex: ['None', 'Blush', 'Freckles', 'Glasses', 'Mustache', 'Earrings'],
};

export default function AvatarBuilder({ open, initial, onCancel, onDone }) {
  const [spec, setSpec] = useState(() => (isBuiltAvatar(initial) ? parseAvatar(initial) : randomAvatar()));
  const [tab, setTab] = useState('hr');

  // reopened: start from the profile's avatar (or a fresh surprise)
  useEffect(() => {
    if (open) setSpec(isBuiltAvatar(initial) ? parseAvatar(initial) : randomAvatar());
  }, [open, initial]);

  const part = PARTS.find((p) => p.key === tab);
  const choose = (i) => setSpec((s) => ({ ...s, [tab]: i }));

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Create your avatar"
      size="md"
      scrollable={false}
      initialFocus=".avatar-builder__options [aria-checked='true']"
      className="avatar-builder-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => onDone(encodeAvatar(spec))}>
            Use this avatar
          </Button>
        </>
      }
    >
      <div className="avatar-builder">
        <div className="avatar-builder__stage">
          <div className="avatar-builder__preview">
            <AvatarArt spec={spec} title="Your avatar" />
          </div>
          <Button variant="glass" size="sm" icon={<DiceIcon />} onClick={() => setSpec(randomAvatar())}>
            Surprise me
          </Button>
        </div>

        <div className="ui-scroller avatar-builder__tabs" role="tablist" aria-label="Avatar parts">
          {TABS.map((p) => (
            <Chip
              key={p.key}
              role="tab"
              aria-selected={tab === p.key}
              selected={tab === p.key}
              onClick={(e) => {
                setTab(p.key);
                e.currentTarget.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
              }}
            >
              {p.label}
            </Chip>
          ))}
        </div>

        <div className={`avatar-builder__options${part.color ? ' is-colors' : ''}`} role="radiogroup" aria-label={part.label}>
          {Array.from({ length: part.count }, (_, i) => {
            const selected = spec[tab] === i;
            const label = OPTION_NAMES[tab]?.[i] || `${part.label} ${i + 1}`;
            return (
              <button
                key={i}
                type="button"
                role="radio"
                aria-checked={selected}
                aria-label={label}
                title={label}
                className={`avatar-builder__option${selected ? ' is-selected' : ''}`}
                onClick={() => choose(i)}
              >
                {part.color ? (
                  <span className="avatar-builder__swatch" style={{ background: SWATCHES[tab](i) }} />
                ) : (
                  <AvatarArt spec={{ ...spec, [tab]: i }} />
                )}
              </button>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
