// src/design/components.js
// Shared UI components (styles: components.css, values: tokens.css). Pages use these instead of
// their own buttons / chips / loaders so the app looks like one product.
import React from "react";
import ReactDOM from "react-dom";
import { Link } from "react-router-dom";
import { AlertIcon, CloseIcon, FilmIcon, StarIcon } from "./icons";

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
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return (
    <Badge tone="rating" className={className} aria-label={`Rated ${n.toFixed(1)} out of 10`}>
      <StarIcon className="ui-badge__star" width="1em" height="1em" />
      {n.toFixed(1)}
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

export function Spinner({ className, label = "Loading" }) {
  return <span className={cx("ui-spinner", className)} role="status" aria-label={label} />;
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

/** Turns API errors into a sentence people can read (no "Request failed with status code 404") */
export function friendlyError(err, what = "this page") {
  const status = err?.response?.status ?? err?.status;
  if (status === 404) return `We couldn't find ${what}. It may have been removed.`;
  if (status === 401 || status === 403) return "Your session has expired. Please sign in again.";
  if (status >= 500) return "Our server is having trouble right now. Please try again in a moment.";
  if (err?.message === "Network Error" || (typeof navigator !== "undefined" && navigator.onLine === false)) {
    return "You seem to be offline. Check your connection and try again.";
  }
  return "Something went wrong. Please try again.";
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
          <button type="button" className="ui-btn ui-btn--ghost ui-btn--icon ui-btn--sm ui-modal__close" aria-label="Close" onClick={onClose}>
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
