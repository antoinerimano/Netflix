// src/design/components.js
// Shared UI components (styles: components.css, values: tokens.css). Pages use these instead of
// their own buttons / chips / loaders so the app looks like one product.
import React from "react";
import ReactDOM from "react-dom";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import i18n from "../i18n";
import { formatNumber } from "../i18n/format";
import { AlertIcon, CheckIcon, CloseIcon, FilmIcon, StarIcon } from "./icons";
import { AvatarArt, isBuiltAvatar, parseAvatar } from "./avatarArt";
import BrandLoader from "./BrandLoader";

const cx = (...parts) => parts.filter(Boolean).join(" ");

/**
 * Button: variant = primary | secondary | glass | ghost | danger, size = sm | md | lg.
 * `to` renders a router Link, `href` a plain link; otherwise a <button>.
 * Icon-only buttons: pass `icon` and `label` (no children): the label is read by screen readers
 * and shown as a small tooltip on hover / TV focus.
 */
export const Button = React.forwardRef(function Button(
  {
    variant = "secondary",
    size = "md",
    icon = null,
    iconRight = null,
    label,
    block = false,
    loading = false,
    pressed,
    to,
    href,
    className,
    children,
    type = "button",
    ...rest
  },
  ref
) {
  const iconOnly = !children && !!icon;
  const classes = cx(
    "ui-btn",
    `ui-btn--${variant}`,
    size !== "md" && `ui-btn--${size}`,
    iconOnly && "ui-btn--icon",
    block && "ui-btn--block",
    loading && "is-loading",
    className
  );
  const a11y = {
    "aria-label": iconOnly ? label : rest["aria-label"],
    "aria-pressed": pressed === undefined ? undefined : !!pressed,
    "aria-busy": loading || undefined,
    "data-label": iconOnly ? label : undefined,
  };
  const content = (
    <>
      {icon ? <span className="ui-btn__icon">{icon}</span> : null}
      {children}
      {iconRight ? <span className="ui-btn__icon">{iconRight}</span> : null}
    </>
  );

  if (to) {
    return (
      <Link ref={ref} to={to} className={classes} {...rest} {...a11y}>
        {content}
      </Link>
    );
  }
  if (href) {
    return (
      <a ref={ref} href={href} className={classes} {...rest} {...a11y}>
        {content}
      </a>
    );
  }
  return (
    <button ref={ref} type={type} className={classes} {...rest} {...a11y}>
      {content}
    </button>
  );
});

/** Chip: filters, seasons, sources. `selected` = current choice. */
export function Chip({ selected = false, className, children, ...rest }) {
  return (
    <button type="button" className={cx("ui-chip", selected && "is-selected", className)} aria-pressed={selected} {...rest}>
      {children}
    </button>
  );
}

/** Badge: small label (HD, TV, NEW, S1E2). tone = default | brand | rating */
export function Badge({ tone = "default", className, children, ...rest }) {
  return (
    <span className={cx("ui-badge", tone !== "default" && `ui-badge--${tone}`, className)} {...rest}>
      {children}
    </span>
  );
}

/** ★ 7.4 */
export function Rating({ value, className }) {
  const { t, i18n: { resolvedLanguage } } = useTranslation();
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  const shown = formatNumber(n, { minimumFractionDigits: 1, maximumFractionDigits: 1 }, resolvedLanguage);
  return (
    <Badge tone="rating" className={className} aria-label={t("rating.outOf10", { value: shown })}>
      <StarIcon className="ui-badge__star" width="1em" height="1em" />
      {shown}
    </Badge>
  );
}

/** Loading placeholder. variant = block | text | circle; width / height any CSS length. */
export function Skeleton({ variant = "block", width, height, radius, className, style }) {
  return (
    <span
      className={cx("ui-skeleton", variant !== "block" && `ui-skeleton--${variant}`, className)}
      style={{ width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  );
}

/** Loading indicator: the animated Taurus emblem (BrandLoader). size in px. */
export function Spinner({ className, label, size = 56 }) {
  return <BrandLoader size={size} label={label} className={className} />;
}

/**
 * Empty / error state: icon, title, one sentence, actions.
 * tone = empty | error; page = fills the screen under the navbar.
 */
export function EmptyState({ tone = "empty", icon, title, children, actions, page = false, className }) {
  const shownIcon = icon || (tone === "error" ? <AlertIcon /> : <FilmIcon />);
  return (
    <div className={cx("ui-empty", tone === "error" && "ui-empty--error", page && "ui-empty--page", className)} role={tone === "error" ? "alert" : undefined}>
      <div className="ui-empty__icon">{shownIcon}</div>
      {title ? <h2 className="ui-empty__title">{title}</h2> : null}
      {children ? <p className="ui-empty__text">{children}</p> : null}
      {actions ? <div className="ui-actions">{actions}</div> : null}
    </div>
  );
}

/** Section heading (rows, detail sections) */
export function SectionTitle({ as: Tag = "h2", className, children, ...rest }) {
  return (
    <Tag className={cx("ui-section-title", className)} {...rest}>
      {children}
    </Tag>
  );
}

/**
 * Turns API errors into a sentence people can read (no "Request failed with status code 404"),
 * in the app's language. what: "page" | "title" | "movie" | "show" | "actor" | "episode"
 * (errors.what.* in locales/<lang>/common.json).
 */
export function friendlyError(err, what = "page") {
  const status = err?.response?.status ?? err?.status;
  if (status === 404) return i18n.t("common:errors.notFound", { context: what });
  if (status === 401 || status === 403) return i18n.t("common:errors.sessionExpired");
  if (status >= 500) return i18n.t("common:errors.server");
  if (err?.message === "Network Error" || (typeof navigator !== "undefined" && navigator.onLine === false)) {
    return i18n.t("common:errors.offline");
  }
  return i18n.t("common:errors.generic");
}

/**
 * Modal dialog: rendered over the page (portal), scrolls inside when the content is long (the
 * header with its close button stays visible), closes with the close button, a click on the
 * backdrop, Escape or the TV remote's Back (tv/spatialNavigation.js: .ui-modal). While open the
 * page behind doesn't scroll and the remote / Tab keys stay inside it; the focus goes back to
 * what opened it when it closes.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
  className,
  initialFocus = ".ui-modal__close", // selector inside the dialog focused when it opens
  scrollable = true, // long text: the body itself can take the focus and scroll with the arrows
}) {
  const { t } = useTranslation();
  const cardRef = React.useRef(null);
  const openerRef = React.useRef(null);
  const titleId = React.useId();

  React.useEffect(() => {
    if (!open) return undefined;
    openerRef.current = document.activeElement;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // focus the close button: Enter / OK closes, arrows move inside
    const t = setTimeout(() => {
      const card = cardRef.current;
      (card?.querySelector(initialFocus) || card?.querySelector(".ui-modal__close"))?.focus({ preventScroll: true });
    }, 0);

    const onKey = (e) => {
      if (e.key === "Tab") {
        // keep Tab inside the dialog
        const items = [...cardRef.current.querySelectorAll('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])')];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      const opener = openerRef.current;
      if (opener && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps -- initialFocus: only when opening

  if (!open) return null;
  const node = (
    <div className="ui-modal" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div
        ref={cardRef}
        className={cx("ui-modal__card", `ui-modal__card--${size}`, className)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
      >
        <header className="ui-modal__header">
          {title ? (
            <h2 id={titleId} className="ui-modal__title">
              {title}
            </h2>
          ) : (
            <span />
          )}
          <button type="button" className="ui-btn ui-btn--ghost ui-btn--icon ui-btn--sm ui-modal__close" aria-label={t("actions.close")} onClick={onClose}>
            <span className="ui-btn__icon">
              <CloseIcon />
            </span>
          </button>
        </header>
        {/* tabIndex: the remote / keyboard can focus the text and scroll it with the arrows */}
        <div className="ui-modal__body" tabIndex={scrollable ? 0 : undefined}>
          {children}
        </div>
        {footer ? <footer className="ui-modal__footer ui-actions">{footer}</footer> : null}
      </div>
    </div>
  );
  return ReactDOM.createPortal(node, document.body);
}

/**
 * Profile avatar: a picture (avatar_url = "/avatars/kid.webp") or a colored tile with the
 * initial (avatar_url = "color:#e50914"). Broken / missing pictures fall back to the tile.
 */
export function Avatar({ src, name = "", size = "2.5rem", className, radius }) {
  const [failed, setFailed] = React.useState(false);
  const isColor = typeof src === "string" && src.startsWith("color:");
  const color = isColor ? src.slice(6) : "#3a3a44";
  const style = { width: size, height: size, borderRadius: radius };
  if (isBuiltAvatar(src)) {
    // made with the avatar builder (design/avatarArt.js)
    return (
      <span className={cx("ui-avatar ui-avatar--art", className)} style={style} aria-hidden="true">
        <AvatarArt spec={parseAvatar(src)} />
      </span>
    );
  }
  if (src && !isColor && !failed) {
    return <img className={cx("ui-avatar", className)} style={style} src={src} alt="" onError={() => setFailed(true)} />;
  }
  return (
    <span className={cx("ui-avatar ui-avatar--initial", className)} style={{ ...style, background: color }} aria-hidden="true">
      {/* SVG: scales with any avatar size and centers the capital exactly (baseline at
          50 + half the cap height, Inter caps ~0.73em); CSS text sat at the top in some boxes */}
      <svg viewBox="0 0 100 100" width="100%" height="100%" focusable="false">
        <text x="50" y="67.5" textAnchor="middle" fontSize="48" fontWeight="800" fill="#ffffff">
          {(name || "?").trim().charAt(0).toUpperCase() || "?"}
        </text>
      </svg>
    </span>
  );
}

/** On / off switch (a button with role="switch": OK on a remote toggles it) */
export function Switch({ checked, onChange, label, description, className, id }) {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={!!checked}
      className={cx("ui-switch", checked && "is-on", className)}
      onClick={() => onChange?.(!checked)}
    >
      <span className="ui-switch__text">
        <span className="ui-switch__label">{label}</span>
        {description ? <span className="ui-switch__desc">{description}</span> : null}
      </span>
      <span className="ui-switch__track" aria-hidden="true">
        <span className="ui-switch__thumb" />
      </span>
    </button>
  );
}

/** Form field: label + control + hint / error */
export function Field({ label, hint, error, children, className, htmlFor }) {
  return (
    <div className={cx("ui-field", error && "has-error", className)}>
      {label ? (
        <label className="ui-field__label" htmlFor={htmlFor}>
          {label}
        </label>
      ) : null}
      {children}
      {error ? (
        <p className="ui-field__error" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="ui-field__hint">{hint}</p>
      ) : null}
    </div>
  );
}

/**
 * Toast: a short confirmation at the bottom of the screen ("Sam saved"), gone by itself.
 * Render it with the current message; onDone clears it.
 */
export function Toast({ message, onDone, duration = 2600, tone = "success" }) {
  React.useEffect(() => {
    if (!message) return undefined;
    const t = setTimeout(() => onDone?.(), duration);
    return () => clearTimeout(t);
  }, [message, duration, onDone]);
  if (!message) return null;
  return ReactDOM.createPortal(
    <div className={cx("ui-toast", `ui-toast--${tone}`)} role="status" aria-live="polite">
      {tone === "error" ? <AlertIcon aria-hidden="true" /> : <CheckIcon aria-hidden="true" />}
      {message}
    </div>,
    document.body
  );
}

export { default as BrandLoader } from "./BrandLoader";
export { default as BrandLogo } from "./BrandLogo";
