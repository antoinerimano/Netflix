// src/design/DesignSystemPage.js
// Living style guide: every token and shared component on one page (/design-system, development
// builds only). Check here first when adding UI: if a piece exists, use it; if not, add it here.
import React, { useState } from "react";
import { Button, Chip, Badge, Rating, Skeleton, Spinner, EmptyState, SectionTitle } from "./components";
import * as Icons from "./icons";
import "./DesignSystemPage.css";

const COLORS = [
  ["Surfaces", ["--color-bg-deep", "--color-bg", "--color-surface-1", "--color-surface-2", "--color-surface-3", "--color-glass"]],
  ["Text", ["--color-text", "--color-text-secondary", "--color-text-muted"]],
  ["Brand & status", ["--color-brand", "--color-brand-hover", "--color-brand-pressed", "--color-success", "--color-warning", "--color-danger", "--color-info", "--color-rating"]],
  ["Borders", ["--color-border-subtle", "--color-border", "--color-border-strong"]],
];
const TYPE = [
  ["--text-4xl", "Hero title", 800],
  ["--text-3xl", "Detail title", 800],
  ["--text-2xl", "Page title", 700],
  ["--text-xl", "Section title", 700],
  ["--text-lg", "Card title / lead", 600],
  ["--text-md", "Body text: the quick brown fox jumps over the lazy dog.", 400],
  ["--text-sm", "Meta · 2024 · 1h 52m · Drama", 500],
  ["--text-xs", "CAPTION · BADGE", 600],
];
const SPACES = ["1", "2", "3", "4", "5", "6", "8", "10", "12", "16"];
const RADII = ["xs", "sm", "md", "lg", "xl", "pill"];
const SHADOWS = ["sm", "md", "lg", "xl"];

function Section({ title, children, note }) {
  return (
    <section className="ds-section">
      <SectionTitle>{title}</SectionTitle>
      {note ? <p className="ds-note">{note}</p> : null}
      {children}
    </section>
  );
}

export default function DesignSystemPage() {
  const [chip, setChip] = useState("All");
  const [inList, setInList] = useState(false);
  const [liked, setLiked] = useState(true);

  return (
    <main className="ds">
      <header className="ds-header">
        <h1>Tauruss design system</h1>
        <p>Tokens: src/design/tokens.css · Components: src/design/components.js · Icons: src/design/icons.js</p>
      </header>

      <Section title="Colors">
        {COLORS.map(([group, vars]) => (
          <div key={group} className="ds-group">
            <h3>{group}</h3>
            <div className="ds-swatches">
              {vars.map((v) => (
                <div key={v} className="ds-swatch">
                  <span className="ds-swatch__color" style={{ background: `var(${v})` }} />
                  <code>{v}</code>
                </div>
              ))}
            </div>
          </div>
        ))}
      </Section>

      <Section title="Typography" note="Inter. Sizes in rem: they grow on TVs (html.tv-device).">
        {TYPE.map(([v, text, weight]) => (
          <div key={v} className="ds-type">
            <code>{v}</code>
            <span style={{ fontSize: `var(${v})`, fontWeight: weight }}>{text}</span>
          </div>
        ))}
      </Section>

      <Section title="Spacing, radii, shadows" note="4 px grid. Pages use --page-gutter on the sides.">
        <div className="ds-spaces">
          {SPACES.map((n) => (
            <div key={n} className="ds-space">
              <span style={{ width: `var(--space-${n})` }} />
              <code>--space-{n}</code>
            </div>
          ))}
        </div>
        <div className="ds-row">
          {RADII.map((r) => (
            <div key={r} className="ds-box" style={{ borderRadius: `var(--radius-${r})` }}>
              <code>--radius-{r}</code>
            </div>
          ))}
        </div>
        <div className="ds-row">
          {SHADOWS.map((s) => (
            <div key={s} className="ds-box ds-box--raised" style={{ boxShadow: `var(--shadow-${s})` }}>
              <code>--shadow-{s}</code>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Buttons" note="One primary per screen. Icon-only buttons need a label (tooltip + screen readers).">
        <div className="ds-row">
          <Button variant="primary" icon={<Icons.PlayIcon />}>Play</Button>
          <Button variant="secondary" icon={<Icons.PlayIcon />}>Resume</Button>
          <Button variant="glass" icon={<Icons.InfoIcon />}>More info</Button>
          <Button variant="ghost">Cancel</Button>
          <Button variant="danger">Delete profile</Button>
        </div>
        <div className="ds-row">
          <Button variant="primary" size="lg" icon={<Icons.PlayIcon />}>Watch</Button>
          <Button variant="primary">Medium</Button>
          <Button variant="primary" size="sm">Small</Button>
          <Button variant="primary" loading>Saving</Button>
          <Button variant="secondary" disabled>Disabled</Button>
        </div>
        <div className="ds-row">
          <Button
            variant="glass"
            icon={inList ? <Icons.CheckIcon /> : <Icons.PlusIcon />}
            pressed={inList}
            label={inList ? "In My List" : "Add to My List"}
            onClick={() => setInList((v) => !v)}
          />
          <Button variant="glass" icon={<Icons.ThumbUpIcon />} pressed={liked} label="I like this" onClick={() => setLiked((v) => !v)} />
          <Button variant="glass" icon={<Icons.ThumbDownIcon />} label="Not for me" />
          <Button variant="glass" icon={<Icons.BellIcon />} label="Notify me" />
          <Button variant="ghost" icon={<Icons.ArrowLeftIcon />} label="Back" />
          <Button variant="glass" size="sm" icon={<Icons.CloseIcon />} label="Close" />
        </div>
      </Section>

      <Section title="Chips & badges">
        <div className="ds-row">
          {["All", "Action", "Comedy", "Drama", "Horror", "Sci-Fi"].map((c) => (
            <Chip key={c} selected={chip === c} onClick={() => setChip(c)}>
              {c}
            </Chip>
          ))}
        </div>
        <div className="ds-row">
          <Badge>HD</Badge>
          <Badge>TV</Badge>
          <Badge>S1 · E4</Badge>
          <Badge tone="brand">NEW</Badge>
          <Rating value={7.4} />
        </div>
      </Section>

      <Section title="Icons" note="currentColor, 24 px grid. No emoji in the UI (they look different on every TV).">
        <div className="ds-icons">
          {Object.entries(Icons).map(([name, Icon]) => (
            <div key={name} className="ds-icon">
              <Icon />
              <code>{name.replace("Icon", "")}</code>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Loading" note="Skeletons in the shape of what is coming, not full-screen spinners.">
        <div className="ds-skeletons">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="ds-skeleton-card">
              <Skeleton style={{ aspectRatio: "16 / 9" }} />
              <Skeleton variant="text" width="70%" />
              <Skeleton variant="text" width="40%" />
            </div>
          ))}
        </div>
        <div className="ds-row">
          <Spinner />
        </div>
      </Section>

      <Section title="Empty & error states">
        <div className="ds-states">
          <EmptyState
            icon={<Icons.PlusIcon />}
            title="Your list is empty"
            actions={<Button variant="primary">Browse movies</Button>}
          >
            Add movies and shows with the + button to find them here later.
          </EmptyState>
          <EmptyState tone="error" title="Show unavailable" actions={<Button variant="ghost">Go back</Button>}>
            We couldn't find this show. It may have been removed.
          </EmptyState>
        </div>
      </Section>
    </main>
  );
}
