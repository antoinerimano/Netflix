// src/components/profiles/AvatarBuilder.js
// "Create your avatar": one tab per area (Hair, Hats, Eyes, Brows, Mouth, Beard, Extras, Face,
// Top, Background), each with its colors (swatches) and its styles (live previews of your own
// character). "Surprise me" + Undo. The preview stays in view: left column on wide screens,
// pinned at the top on phones. Remote: a tab opens as soon as it's focused; Down goes to its
// colors, then its styles; every row lands on its current choice.
import React, { useEffect, useState } from 'react';
import { Button, Chip, Modal } from '../../design';
import { DiceIcon, ArrowLeftIcon } from '../../design/icons';
import {
  AvatarArt, BACKGROUNDS, SKINS, HAIR_COLORS, CLOTH_COLORS, partByKey, encodeAvatar, parseAvatar, randomAvatar, isBuiltAvatar,
} from '../../design/avatarArt';

const COLOR_FILL = {
  bg: (i) => `linear-gradient(135deg, ${BACKGROUNDS[i][0]}, ${BACKGROUNDS[i][1]})`,
  sk: (i) => SKINS[i],
  hc: (i) => HAIR_COLORS[i],
  hwc: (i) => CLOTH_COLORS[i],
  sh: (i) => CLOTH_COLORS[i],
};
const TABS = [
  { id: 'hair', label: 'Hair', color: 'hc', style: 'hr' },
  { id: 'hat', label: 'Hats', color: 'hwc', style: 'hw' },
  { id: 'eyes', label: 'Eyes', style: 'ey' },
  { id: 'brows', label: 'Brows', style: 'eb' },
  { id: 'mouth', label: 'Mouth', style: 'mo' },
  { id: 'beard', label: 'Beard', style: 'bd' },
  { id: 'extras', label: 'Extras', style: 'ex' },
  { id: 'face', label: 'Face', color: 'sk', style: 'fc' },
  { id: 'top', label: 'Top', color: 'sh', style: 'ts' },
  { id: 'scene', label: 'Background', color: 'bg', style: 'pt' },
];
const COLOR_NAMES = { hc: 'Hair color', hwc: 'Hat color', sk: 'Skin', sh: 'Color', bg: 'Colors' };

export default function AvatarBuilder({ open, initial, onCancel, onDone }) {
  const [spec, setSpec] = useState(() => (isBuiltAvatar(initial) ? parseAvatar(initial) : randomAvatar()));
  const [history, setHistory] = useState([]); // previous specs ("Surprise me" can be undone)
  const [tabId, setTabId] = useState('hair');

  useEffect(() => {
    if (!open) return;
    setSpec(isBuiltAvatar(initial) ? parseAvatar(initial) : randomAvatar());
    setHistory([]);
    setTabId('hair');
  }, [open, initial]);

  const tab = TABS.find((t) => t.id === tabId);
  const update = (patch) => {
    setHistory((h) => [...h.slice(-19), spec]);
    setSpec((s) => ({ ...s, ...patch }));
  };
  const surprise = () => {
    setHistory((h) => [...h.slice(-19), spec]);
    setSpec(randomAvatar());
  };
  const undo = () => {
    if (!history.length) return;
    setSpec(history[history.length - 1]);
    setHistory((h) => h.slice(0, -1));
  };
  const openTab = (id, el) => {
    setTabId(id);
    // keep the tab inside its row, sideways only: a vertical scrollIntoView fought the remote's
    // own scrolling of the sheet (which keeps items clear of the pinned preview)
    const row = el?.parentElement;
    if (!row) return;
    const r = el.getBoundingClientRect();
    const box = row.getBoundingClientRect();
    if (r.left < box.left + 24) row.scrollLeft += r.left - box.left - 24;
    else if (r.right > box.right - 24) row.scrollLeft += r.right - box.right + 24;
  };

  const styleKey = tab.style;
  const stylePart = partByKey[styleKey];

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Create your avatar"
      size="lg"
      scrollable={false}
      initialFocus=".avatar-builder__tabs [aria-selected='true']"
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
          <div className="avatar-builder__stage-actions">
            <Button variant="glass" size="sm" icon={<DiceIcon />} onClick={surprise}>
              Surprise me
            </Button>
            <Button variant="ghost" size="sm" icon={<ArrowLeftIcon />} onClick={undo} disabled={!history.length}>
              Undo
            </Button>
          </div>
        </div>

        <div className="avatar-builder__panel">
          <div className="ui-scroller avatar-builder__tabs" role="tablist" aria-label="Avatar parts">
            {TABS.map((t) => (
              <Chip
                key={t.id}
                role="tab"
                id={`avb-tab-${t.id}`}
                aria-selected={tabId === t.id}
                aria-controls="avb-panel"
                selected={tabId === t.id}
                // remote / keyboard: the tab opens as soon as it's focused (no OK needed)
                onFocus={(e) => tabId !== t.id && openTab(t.id, e.currentTarget)}
                onClick={(e) => openTab(t.id, e.currentTarget)}
              >
                {t.label}
              </Chip>
            ))}
          </div>

          <div id="avb-panel" role="tabpanel" aria-labelledby={`avb-tab-${tabId}`} className="avatar-builder__tabpanel" key={tabId}>
            {tab.color ? (
              <section className="avatar-builder__group">
                <h3 className="avatar-builder__label">{COLOR_NAMES[tab.color]}</h3>
                <div className="ui-scroller avatar-builder__colors" role="radiogroup" aria-label={COLOR_NAMES[tab.color]}>
                  {Array.from({ length: partByKey[tab.color].count }, (_, i) => (
                    <button
                      key={i}
                      type="button"
                      role="radio"
                      aria-checked={spec[tab.color] === i}
                      aria-label={`${COLOR_NAMES[tab.color]} ${i + 1}`}
                      className={`avatar-builder__swatch${spec[tab.color] === i ? ' is-selected' : ''}`}
                      style={{ background: COLOR_FILL[tab.color](i) }}
                      onClick={() => update({ [tab.color]: i })}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            <section className="avatar-builder__group">
              <h3 className="avatar-builder__label">{tab.color ? 'Style' : stylePart.label}</h3>
              <div className="avatar-builder__options" role="radiogroup" aria-label={stylePart.label}>
                {Array.from({ length: stylePart.count }, (_, i) => {
                  const selected = spec[styleKey] === i;
                  const name = stylePart.names?.[i] || `${stylePart.label} ${i + 1}`;
                  return (
                    <button
                      key={i}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      aria-label={name}
                      title={name}
                      className={`avatar-builder__option${selected ? ' is-selected' : ''}`}
                      onClick={() => update({ [styleKey]: i })}
                    >
                      <AvatarArt spec={{ ...spec, [styleKey]: i }} />
                      <span className="avatar-builder__option-name">{name}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          </div>
        </div>
      </div>
    </Modal>
  );
}
