// src/components/profiles/AvatarBuilder.js
// "Create your avatar": one tab per area (Hair, Hats, Eyes, Brows, Mouth, Beard, Extras, Face,
// Top, Background), each with its colors (swatches) and its styles (live previews of your own
// character). "Surprise me" + Undo. The preview stays in view: left column on wide screens,
// pinned at the top on phones. Remote: a tab opens as soon as it's focused; Down goes to its
// colors, then its styles; every row lands on its current choice.
import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
// labels: profiles:avatar.tabs.<id>, avatar.colors.<color>, avatar.parts.<key>, avatar.names.<key>[i]
const TABS = [
  { id: 'hair', color: 'hc', style: 'hr' },
  { id: 'hat', color: 'hwc', style: 'hw' },
  { id: 'eyes', style: 'ey' },
  { id: 'brows', style: 'eb' },
  { id: 'mouth', style: 'mo' },
  { id: 'beard', style: 'bd' },
  { id: 'extras', style: 'ex' },
  { id: 'face', color: 'sk', style: 'fc' },
  { id: 'top', color: 'sh', style: 'ts' },
  { id: 'scene', color: 'bg', style: 'pt' },
];

export default function AvatarBuilder({ open, initial, onCancel, onDone }) {
  const { t } = useTranslation('profiles');
  const [spec, setSpec] = useState(() => (isBuiltAvatar(initial) ? parseAvatar(initial) : randomAvatar()));
  const [history, setHistory] = useState([]); // previous specs ("Surprise me" can be undone)
  const [tabId, setTabId] = useState('hair');

  useEffect(() => {
    if (!open) return;
    setSpec(isBuiltAvatar(initial) ? parseAvatar(initial) : randomAvatar());
    setHistory([]);
    setTabId('hair');
  }, [open, initial]);

  const tab = TABS.find((x) => x.id === tabId);
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
  const styleLabel = t(`avatar.parts.${styleKey}`, { defaultValue: stylePart.label });
  const styleNames = t(`avatar.names.${styleKey}`, { returnObjects: true, defaultValue: stylePart.names || [] });
  const colorLabel = tab.color ? t(`avatar.colors.${tab.color}`) : '';

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={t('avatar.title')}
      size="lg"
      scrollable={false}
      initialFocus=".avatar-builder__tabs [aria-selected='true']"
      className="avatar-builder-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            {t('actions.cancel')}
          </Button>
          <Button variant="primary" onClick={() => onDone(encodeAvatar(spec))}>
            {t('avatar.use')}
          </Button>
        </>
      }
    >
      <div className="avatar-builder">
        <div className="avatar-builder__stage">
          <div className="avatar-builder__preview">
            <AvatarArt spec={spec} title={t('form.ownAvatar')} />
          </div>
          <div className="avatar-builder__stage-actions">
            <Button variant="glass" size="sm" icon={<DiceIcon />} onClick={surprise}>
              {t('avatar.surprise')}
            </Button>
            <Button variant="ghost" size="sm" icon={<ArrowLeftIcon />} onClick={undo} disabled={!history.length}>
              {t('avatar.undo')}
            </Button>
          </div>
        </div>

        <div className="avatar-builder__panel">
          <div className="ui-scroller avatar-builder__tabs" role="tablist" aria-label={t('avatar.partsLabel')}>
            {TABS.map((x) => (
              <Chip
                key={x.id}
                role="tab"
                id={`avb-tab-${x.id}`}
                aria-selected={tabId === x.id}
                aria-controls="avb-panel"
                selected={tabId === x.id}
                // remote / keyboard: the tab opens as soon as it's focused (no OK needed)
                onFocus={(e) => tabId !== x.id && openTab(x.id, e.currentTarget)}
                onClick={(e) => openTab(x.id, e.currentTarget)}
              >
                {t(`avatar.tabs.${x.id}`)}
              </Chip>
            ))}
          </div>

          <div id="avb-panel" role="tabpanel" aria-labelledby={`avb-tab-${tabId}`} className="avatar-builder__tabpanel" key={tabId}>
            {tab.color ? (
              <section className="avatar-builder__group">
                <h3 className="avatar-builder__label">{colorLabel}</h3>
                <div className="ui-scroller avatar-builder__colors" role="radiogroup" aria-label={colorLabel}>
                  {Array.from({ length: partByKey[tab.color].count }, (_, i) => (
                    <button
                      key={i}
                      type="button"
                      role="radio"
                      aria-checked={spec[tab.color] === i}
                      aria-label={t('avatar.numbered', { label: colorLabel, number: i + 1 })}
                      className={`avatar-builder__swatch${spec[tab.color] === i ? ' is-selected' : ''}`}
                      style={{ background: COLOR_FILL[tab.color](i) }}
                      onClick={() => update({ [tab.color]: i })}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            <section className="avatar-builder__group">
              <h3 className="avatar-builder__label">{tab.color ? t('avatar.style') : styleLabel}</h3>
              <div className="avatar-builder__options" role="radiogroup" aria-label={styleLabel}>
                {Array.from({ length: stylePart.count }, (_, i) => {
                  const selected = spec[styleKey] === i;
                  const name = (Array.isArray(styleNames) && styleNames[i]) || t('avatar.numbered', { label: styleLabel, number: i + 1 });
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
