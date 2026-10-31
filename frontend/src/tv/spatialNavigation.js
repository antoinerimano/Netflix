// src/tv/spatialNavigation.js
// TV remote / keyboard navigation for the whole site, without touching each page:
//   arrows  -> focus the nearest focusable element in that direction (by position on screen)
//   Enter   -> activate it (div / li "buttons" get a click(), links and buttons work natively)
//   Back    -> previous page (TV remote Back key: Tizen, webOS, Android TV)
// Mouse users see no difference. Text fields keep left / right for the cursor. A video player
// that takes the focus by itself gives it back (see onWindowBlur).

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(","); // not iframes: once inside a cross-origin player, the arrows can't bring you back out

const DIRECTIONS = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
// TV remotes' Back button. Escape only closes menus; Backspace is left alone (text editing).
const BACK_KEYS = new Set(["GoBack", "BrowserBack"]);
const BACK_KEY_CODES = new Set([10009 /* Samsung Tizen */, 461 /* LG webOS */]);
const NATIVE_ENTER = "a[href], button, input, select, textarea, summary";
const TOP_MARGIN = 90; // keep focused elements below the navbar
const COMFORT_BOTTOM = 0.85; // scroll before the focus gets closer than this to the bottom

// Controls a remote adjusts with the arrows once "entered" with OK (red ring, .tv-editing):
// otherwise the arrows would always move the focus away and the value could never change.
const ADJUSTABLE = "input[type='number'], input[type='range'], input[type='date'], input[type='time']";
let editing = null;

function stopEditing() {
  editing?.classList.remove("tv-editing");
  editing = null;
}

/** True when the arrows should change this control's value (not move the focus):
 *  entered with OK on a remote, or clicked with the mouse. Components with their own
 *  arrow handlers (e.g. a year field) check this first. */
export function isEditing(el) {
  return !!el && el === editing;
}

// Cards with their own buttons (⊘ not interested, ✕ remove): hold OK to reach them
const CARD_WITH_ACTIONS = ".movie-card";
const CARD_ACTION = ".row-remove-btn";
const HOLD_MS = 550;
let enterHold = null; // { el, timer, held }

function isTyping(el) {
  return !!el?.matches?.("input, textarea, select, [contenteditable='true']");
}

function atTextEdge(el, dir) {
  if (el.tagName === "SELECT") return true; // a select uses up / down, not left / right
  let start;
  let end;
  try {
    start = el.selectionStart;
    end = el.selectionEnd;
  } catch {
    return true; // inputs without a text cursor (checkbox, number in some browsers...)
  }
  if (start == null) return true;
  const length = (el.value || "").length;
  return start === end && (dir === "left" ? start === 0 : end === length);
}

function candidates() {
  return [...document.querySelectorAll(FOCUSABLE)].filter((el) => {
    if (el.closest(".slick-cloned, [inert]")) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const style = window.getComputedStyle(el);
    return style.visibility !== "hidden" && style.pointerEvents !== "none";
  });
}

function center(r) {
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

/** Nearest candidate in a direction; elements in the same row / column win over diagonal ones. */
function nearest(from, dir, list) {
  const a = from.getBoundingClientRect();
  const ca = center(a);
  let best = null;
  let bestScore = Infinity;
  for (const el of list) {
    if (el === from || el.contains(from) || from.contains(el)) continue;
    const b = el.getBoundingClientRect();
    const cb = center(b);
    const dx = cb.x - ca.x;
    const dy = cb.y - ca.y;
    let main;
    let cross;
    let aligned;
    if (dir === "right" || dir === "left") {
      main = dir === "right" ? dx : -dx;
      cross = Math.abs(dy);
      aligned = b.top < a.bottom && b.bottom > a.top;
    } else {
      main = dir === "down" ? dy : -dy;
      cross = Math.abs(dx);
      aligned = b.left < a.right && b.right > a.left;
    }
    if (main <= 1) continue; // not in that direction
    // left / right stay on the same line (end of a row: stay there, like a TV)
    if (!aligned && (dir === "left" || dir === "right")) continue;
    const score = main + (aligned ? 0 : 2 * cross + 1000);
    if (score < bestScore) {
      bestScore = score;
      best = el;
    }
  }
  return best;
}

// The page's main action, then its content, when nothing is focused yet
const START_SELECTORS = [
  ".hero-button, .movie-detail-play-button, .tvd-play", // Play / Watch
  ".movie-card, .ps-store-movie-card, .tvd-ep-card", // cards
];

// Groups remember their position: going down to the next row and back up returns to the card
// you were on (like TV apps), and entering a group lands on its current item (season shown,
// source playing, active profile) rather than whatever happens to be closest.
const GROUPS = ".row, .tvd-seasons__chips, .watchpage__providerRow, .nav-links, .profile-dropdown";
const CURRENT_IN_GROUP = ".is-active, .selected, [aria-pressed='true'], [aria-current='page']";
const lastInGroup = new WeakMap();

function usable(el) {
  if (!el?.isConnected || !el.matches(FOCUSABLE)) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && window.getComputedStyle(el).pointerEvents !== "none";
}

function preferInGroup(from, next) {
  const group = next.closest(GROUPS);
  if (!group || group.contains(from)) return next; // moving inside a group: by position
  const remembered = lastInGroup.get(group);
  if (group.contains(remembered) && usable(remembered)) return remembered;
  const current = [...group.querySelectorAll(CURRENT_IN_GROUP)].find(usable);
  return current || next;
}

function startingPoint(list) {
  const onScreen = (el) => {
    const r = el.getBoundingClientRect();
    return r.bottom > TOP_MARGIN && r.top < window.innerHeight;
  };
  for (const selector of START_SELECTORS) {
    const match = list.filter((el) => el.matches(selector));
    const pick = match.find(onScreen) || match[0];
    if (pick) return pick;
  }
  return list.find((el) => onScreen(el) && el.getBoundingClientRect().top >= TOP_MARGIN) || list[0];
}

// Focus can be lost without the user moving (an ad, a popup or the player iframe takes it):
// continue from where they were instead of starting the page over.
let lastFocused = null;

// Embedded players grab the focus when they start (autoplay): every key then goes to the player
// (cross-origin, we can't see them) and a remote user is stuck in it. Give the focus back unless
// the user went there: the mouse is over the player (a click) or we moved there with the arrows.
let pointerOverIframe = false;
let enteringIframe = false;
let lastRestore = 0;

function onKeyUp(e) {
  if (e.key !== "Enter" || !enterHold) return;
  const hold = enterHold;
  enterHold = null;
  clearTimeout(hold.timer);
  if (!hold.held && document.activeElement === hold.el) hold.el.click(); // short press: open the card
}

function onWindowBlur() {
  setTimeout(() => {
    const el = document.activeElement;
    if (el?.tagName !== "IFRAME" || pointerOverIframe || enteringIframe) return;
    if (Date.now() - lastRestore < 1000) return; // don't fight a player that keeps taking it
    lastRestore = Date.now();
    const back = lastFocused && lastFocused !== el && lastFocused.isConnected ? lastFocused : startingPoint(candidates());
    back?.focus({ preventScroll: true });
  }, 0);
}

/** Hand the remote to an embedded player on purpose (watch page "Full screen"): keys then go to
 *  the player (OK = play / pause), Back leaves full screen. */
export function enterPlayer(iframe) {
  if (!iframe) return;
  enteringIframe = true;
  setTimeout(() => {
    enteringIframe = false;
  }, 1000);
  iframe.focus();
}

function focusElement(el) {
  el.focus({ preventScroll: true });
  // scroll the page vertically only: scrolling horizontally would break the row sliders
  const r = el.getBoundingClientRect();
  const panel = el.closest(".search-results, .notif__panel, .profile-dropdown");
  if (panel) {
    // inside a dropdown: scroll the dropdown itself, vertically only (scrollIntoView could also
    // scroll the page sideways)
    const p = panel.getBoundingClientRect();
    if (r.top < p.top) panel.scrollTop -= p.top - r.top;
    else if (r.bottom > p.bottom) panel.scrollTop += r.bottom - p.bottom;
  } else if (r.top < TOP_MARGIN || r.bottom > window.innerHeight * COMFORT_BOTTOM) {
    // near an edge: bring it to a steady spot ~40% down the screen (TV apps keep the active
    // row in place), or just under the navbar if it is taller than that
    const target = Math.max(TOP_MARGIN, Math.min(window.innerHeight * 0.4, window.innerHeight - r.height - 20));
    window.scrollBy({ top: r.top - target, behavior: "smooth" });
  }
}

// Open menus close with Back / Escape before Back means "previous page"
const POPUPS = [
  { panel: ".profile-dropdown", toggle: ".profile-icon" },
  { panel: ".notif__panel", toggle: ".notif__button" },
];

function closePopup(active) {
  for (const { panel, toggle } of POPUPS) {
    if (document.querySelector(panel)) {
      const button = document.querySelector(toggle);
      button?.click(); // the toggle closes it
      button?.focus({ preventScroll: true });
      return true;
    }
  }
  const search = active?.closest(".search-profile");
  if (search && search.querySelector(".search-result-item")) {
    if (active.matches("input")) active.blur(); // results hide once focus leaves the search box
    else search.querySelector("input")?.focus({ preventScroll: true }); // back to the query
    return true;
  }
  return false;
}

function onKeyDown(e) {
  if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
  let active = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
  if (!active && lastFocused?.isConnected && lastFocused.getBoundingClientRect().width > 0) active = lastFocused;
  const typing = isTyping(active);

  // a control being adjusted: arrows change its value, OK / Back / Escape leave the edit mode
  if (editing) {
    if (editing !== active) stopEditing();
    else if (DIRECTIONS[e.key]) return;
    else if (
      (e.key === "Enter" && editing.classList.contains("tv-editing")) || // remote: OK confirms
      e.key === "Escape" || BACK_KEYS.has(e.key) || BACK_KEY_CODES.has(e.keyCode)
    ) {
      e.preventDefault();
      stopEditing();
      return;
    }
  }

  const dir = DIRECTIONS[e.key];
  if (dir) {
    // in a text field, left / right move the cursor, and only leave the field from its ends
    // (an empty field is left right away): otherwise a remote user is stuck in the search box
    if (typing && (dir === "left" || dir === "right") && !atTextEdge(active, dir)) return;
    const list = candidates();
    let next = active ? nearest(active, dir, list) : startingPoint(list);
    if (next && active && (dir === "up" || dir === "down")) next = preferInGroup(active, next);
    if (next) {
      e.preventDefault(); // no page scroll: we scroll to the focused element ourselves
      focusElement(next);
    }
    return;
  }

  if (e.key === "Enter" && active) {
    if (active.matches("select")) {
      // OK opens the list (TV browsers / recent Chrome); arrows inside the open list are native
      e.preventDefault();
      try {
        active.showPicker();
      } catch {
        editing = active; // no picker API: adjust with the arrows instead
        active.classList.add("tv-editing");
      }
      return;
    }
    if (active.matches(ADJUSTABLE)) {
      e.preventDefault();
      editing = active;
      active.classList.add("tv-editing");
      return;
    }
    if (active.matches("input[type='checkbox'], input[type='radio']")) {
      e.preventDefault();
      active.click();
      return;
    }
    if (!typing && active.matches(CARD_WITH_ACTIONS) && active.querySelector(CARD_ACTION)) {
      // short press = open the card (on key up), long press = go to its ⊘ / ✕ button
      e.preventDefault();
      if (!enterHold || enterHold.el !== active) {
        const hold = { el: active, held: false };
        hold.timer = setTimeout(() => {
          hold.held = true;
          active.querySelector(CARD_ACTION)?.focus({ preventScroll: true });
        }, HOLD_MS);
        enterHold = hold;
      }
      return;
    }
    if (!typing && !active.matches(NATIVE_ENTER)) {
      e.preventDefault();
      active.click(); // div / li with onClick and tabIndex (cards, menu items)
      return;
    }
  }

  // Back / Escape from a card's ⊘ / ✕ button: back to the card
  const ownerCard = active?.matches(CARD_ACTION) ? active.closest(CARD_WITH_ACTIONS) : null;

  if (e.key === "Escape") {
    if (ownerCard) {
      e.preventDefault();
      ownerCard.focus({ preventScroll: true });
    } else if (closePopup(active)) e.preventDefault();
    return;
  }

  if (BACK_KEYS.has(e.key) || BACK_KEY_CODES.has(e.keyCode)) {
    e.preventDefault();
    if (ownerCard) ownerCard.focus({ preventScroll: true });
    else if (!closePopup(active) && window.location.pathname !== "/") window.history.back();
  }
}

let started = false;
export function startSpatialNavigation() {
  if (started || typeof window === "undefined") return;
  started = true;
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("keyup", onKeyUp);
  document.addEventListener("focusin", (e) => {
    lastFocused = e.target;
    const group = e.target.closest?.(GROUPS);
    if (group) lastInGroup.set(group, e.target);
  });
  document.addEventListener("focusout", (e) => {
    if (e.target === editing) stopEditing();
  });
  // clicked with the mouse: arrows behave natively in this control (no red "remote" ring)
  document.addEventListener("pointerdown", (e) => {
    const control = e.target.closest?.(`${ADJUSTABLE}, select`);
    if (control && control !== editing) {
      stopEditing();
      editing = control;
    }
  });
  window.addEventListener("blur", onWindowBlur);
  document.addEventListener("mouseover", (e) => {
    pointerOverIframe = e.target?.tagName === "IFRAME";
  });
}
