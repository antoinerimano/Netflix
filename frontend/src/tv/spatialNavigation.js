// src/tv/spatialNavigation.js
// TV remote / keyboard navigation for the whole site, without touching each page:
//   arrows  -> focus the nearest focusable element in that direction (by position on screen)
//   Enter   -> activate it (div / li "buttons" get a click(), links and buttons work natively)
//   Back    -> previous page (TV remote Back key: Tizen, webOS, Android TV, and Escape on a
//              keyboard): closes an open menu / leaves full screen first
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
// TV remotes' Back button, and Escape (same meaning). Backspace is left alone (text editing).
const BACK_KEYS = new Set(["GoBack", "BrowserBack", "Escape"]);
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

// Cards with an options sheet (data-options): hold OK, or press the remote's menu key, to open it.
// The card receives a "contextmenu" event, like a right click / long press, and opens its sheet.
const CARD_WITH_ACTIONS = "[data-options]";
const HOLD_MS = 550;
const MENU_KEYS = new Set(["ContextMenu", "Menu", "Info", "ColorF3Blue"]);

// OK still held after the sheet opened: its repeats must not press the sheet's first item (Play).
// Some remotes repeat without e.repeat, so Enter is ignored until the key is released.
let swallowEnter = false;

function openOptions(card) {
  const r = card.getBoundingClientRect();
  card.dispatchEvent(
    new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 })
  );
}
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

function openModal() {
  const all = document.querySelectorAll(".ui-modal");
  return all.length ? all[all.length - 1] : null;
}

// An open dropdown (profile menu, notifications): its items and its button only, so the arrows
// can't wander to the page behind it while it stays open. Back / Escape closes it.
function openMenu() {
  for (const { panel, toggle } of POPUPS) {
    const el = document.querySelector(panel);
    if (el) return el.closest(".profile-container, .notif") || el.parentElement || document.querySelector(toggle)?.parentElement;
  }
  return null;
}

function fullscreenElement() {
  return document.fullscreenElement || document.webkitFullscreenElement || null;
}

function candidates() {
  // in full screen / an open dialog only what is shown can be reached (the rest of the page is
  // still laid out behind it)
  const root = fullscreenElement() || openModal() || openMenu() || document;
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => {
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
// Areas that scroll by themselves: what's scrolled out of view inside them is further down /
// up than the buttons fixed around them (a dialog's footer), but comes first
const SCROLL_AREAS = ".ui-modal__body, .search-results, .notif__panel, .profile-dropdown";

function nearest(from, dir, list) {
  const a = from.getBoundingClientRect();
  const ca = center(a);
  const area = from.closest(SCROLL_AREAS);
  let best = null;
  let bestScore = Infinity;
  for (const el of list) {
    if (el === from || el.contains(from)) continue;
    if (from.contains(el) && from.matches(CARD_WITH_ACTIONS)) continue; // card buttons: hold OK
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
    // leave the scrolling area (e.g. for the dialog's buttons) only when nothing is left in it
    const outside = area && !area.contains(el) ? 100000 : 0;
    const score = main + (aligned ? 0 : 2 * cross + 1000) + outside;
    if (score < bestScore) {
      bestScore = score;
      best = el;
    }
  }
  return best;
}

// The page's main action, then its content, when nothing is focused yet
const START_SELECTORS = [
  ".profile-tile, .ui-btn--primary, .hero-button, .movie-detail-play-button, .tvd-play, .watchpage__playerWrap[tabindex='0']", // Play / Watch
  ".movie-card, .poster-card, .tvd-ep-card", // cards
];

// Groups remember their position: going down to the next row and back up returns to the card
// you were on (like TV apps), and entering a group lands on its current item (season shown,
// source playing, active profile) rather than whatever happens to be closest.
const GROUPS = ".row, .profiles__grid, .profile-form__pictures, .profile-form__letter-colors, .profile-form__chips, .avatar-builder__tabs, .avatar-builder__colors, .avatar-builder__options, .detail-similar, .detail-cast, .tvd-seasons__chips, .browse__genres, .browse-filters__chips, .watchpage__providerRow, .nav-links, .profile-dropdown";
const CURRENT_IN_GROUP = ".is-active, .selected, .is-selected, [aria-pressed='true'], [aria-checked='true'], [aria-selected='true'], [aria-current='page']";
const lastInGroup = new WeakMap();

function usable(el) {
  if (!el?.isConnected || !el.matches(FOCUSABLE)) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && window.getComputedStyle(el).pointerEvents !== "none";
}

// End of a line in a group that wraps (chips, color / style grids): right continues with the next
// item of the group, left with the previous one, like TV grids. (Without it, the items on the
// next line could be unreachable: nothing is aligned with them from the end of the line above.)
// Rows that slide (home rows) stop at their ends instead.
function wrapInGroup(from, dir, list) {
  const group = from.closest(GROUPS);
  if (!group || group.matches(".row")) return null;
  const items = list.filter((el) => group.contains(el) && el.closest(GROUPS) === group);
  const i = items.indexOf(from);
  if (i < 0) return null;
  return items[dir === "right" ? i + 1 : i - 1] || null;
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
  if (e.key === "Enter") swallowEnter = false;
  if (e.key !== "Enter" || !enterHold) return;
  const hold = enterHold;
  enterHold = null;
  clearTimeout(hold.timer);
  if (!hold.held && document.activeElement === hold.el) hold.el.click(); // short press: open the card
}

function onWindowBlur() {
  setTimeout(() => {
    const el = document.activeElement;
    if (el?.tagName !== "IFRAME" || enteringIframe || inPlayer) return;
    if (pointerOverIframe && !keyboardMode) return; // clicked into the player with the mouse
    if (Date.now() - lastRestore < 1000) return; // don't fight a player that keeps taking it
    lastRestore = Date.now();
    const back = lastFocused && lastFocused !== el && lastFocused.isConnected ? lastFocused : startingPoint(candidates());
    back?.focus({ preventScroll: true });
  }, 0);
}

/** Hand the remote to the player on purpose (watch page "Full screen"): keys then go to the
 *  player (OK = play / pause), Back / Escape leaves full screen and gives the remote back to the
 *  page (see onFullscreenChange). Works with an embedded player (iframe) or a <video>. */
let inPlayer = false;
let returnFocusTo = null;
export function enterPlayer(player) {
  if (!player) return;
  const active = document.activeElement;
  if (active && active !== document.body && active.tagName !== "IFRAME") returnFocusTo = active;
  enteringIframe = true;
  setTimeout(() => {
    enteringIframe = false;
  }, 1000);
  if (player.tagName === "VIDEO" && !player.hasAttribute("tabindex")) player.tabIndex = -1;
  player.focus({ preventScroll: true });
}

// Leaving full screen (Escape / Back, which the browser handles even inside a cross-origin
// player, or the player's own button) left the focus inside the player: every key then went to
// it and the remote was stuck there. Take the focus back to where the user was.
let lastFullscreenExit = 0;
function onFullscreenChange() {
  if (fullscreenElement()) {
    inPlayer = true;
    return;
  }
  inPlayer = false;
  lastFullscreenExit = Date.now();
  const restore = () => {
    const el = document.activeElement;
    const stuck = !el || el === document.body || el.tagName === "IFRAME" || el.tagName === "VIDEO";
    if (!stuck && document.hasFocus()) return;
    window.focus();
    const back =
      (returnFocusTo && usable(returnFocusTo) && returnFocusTo) ||
      document.querySelector(".watchpage__fullscreenBtn") ||
      startingPoint(candidates());
    back?.focus({ preventScroll: true });
  };
  setTimeout(restore, 0);
  setTimeout(restore, 300); // some players take the focus back while leaving full screen
}

// Pages can give Back their own meaning (the watch page returns to the title's details page)
let backHandler = null;
export function setBackHandler(fn) {
  backHandler = fn;
  return () => {
    if (backHandler === fn) backHandler = null;
  };
}

function goBack() {
  if (fullscreenElement()) {
    (document.exitFullscreen || document.webkitExitFullscreen)?.call(document)?.catch?.(() => {});
    return;
  }
  // the key that left full screen (some browsers also send it to the page): not a second Back
  if (Date.now() - lastFullscreenExit < 600) return;
  if (backHandler) {
    backHandler();
    return;
  }
  if (window.location.pathname === "/") return;
  // react-router keeps the position in the history: nothing to go back to (link opened directly)
  if ((window.history.state?.idx ?? 1) > 0) window.history.back();
  else window.location.assign("/");
}

// A row that scrolls sideways (genre / season chips, cast): keep the focused item inside it
function revealHorizontally(el) {
  const row = el.parentElement?.closest(".ui-scroller, .detail-scroller, .detail-cast");
  if (!row || row.scrollWidth <= row.clientWidth) return;
  const r = el.getBoundingClientRect();
  const box = row.getBoundingClientRect();
  const margin = 32; // past the faded edges
  // instant, like dialogs: a smooth scroll inside an overflow box doesn't always run
  if (r.left < box.left + margin) row.scrollLeft += r.left - box.left - margin;
  else if (r.right > box.right - margin) row.scrollLeft += r.right - box.right + margin;
}

function focusElement(el) {
  el.focus({ preventScroll: true });
  revealHorizontally(el);
  // scroll the page vertically only: scrolling horizontally would break the row sliders
  const r = el.getBoundingClientRect();
  const panel = el.closest(".search-results, .notif__panel, .profile-dropdown, .ui-modal__body");
  if (panel) {
    // inside a dropdown / dialog: scroll it, vertically only (scrollIntoView could also scroll the
    // page sideways), keeping a margin and staying clear of a header pinned inside it
    const p = panel.getBoundingClientRect();
    // a pinned header above the item (the avatar preview on phones; on wide screens it's a
    // column beside the choices and doesn't count)
    // (and a bar pinned at the bottom: a form's Save / Cancel)
    const pinnedBox = (sel) =>
      [...panel.querySelectorAll(sel)]
        .filter((x) => window.getComputedStyle(x).position === "sticky" && !x.contains(el))
        .map((x) => x.getBoundingClientRect())
        .find((b) => b.left < r.right && b.right > r.left);
    const pinned = pinnedBox(".avatar-builder__stage");
    const pinnedBottom = pinnedBox(".profile-form__actions");
    const top = p.top + (pinned ? pinned.height : 0) + 20;
    const bottom = p.bottom - (pinnedBottom ? pinnedBottom.height : 0) - 20;
    // instant: short distances, and a smooth scroll inside an overflow box doesn't always run
    // (it stayed put in some browsers / TV engines, leaving the focused item hidden)
    if (r.top < top) panel.scrollTop += r.top - top;
    else if (r.bottom > bottom) panel.scrollTop += r.bottom - bottom;
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
  const modal = openModal();
  if (modal) {
    modal.querySelector(".ui-modal__close")?.click(); // the dialog puts the focus back itself
    return true;
  }
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

// "Keyboard mode" while the remote / arrows are used: hover effects off (a card under a
// resting mouse pointer looked selected too) and the pointer hidden. Moving the mouse ends it.
let keyboardMode = false;
function setKeyboardMode(on) {
  if (on === keyboardMode) return;
  keyboardMode = on;
  document.documentElement.classList.toggle("tv-keys", on);
}

function onKeyDown(e) {
  if (DIRECTIONS[e.key] || e.key === "Enter" || BACK_KEYS.has(e.key) || BACK_KEY_CODES.has(e.keyCode)) {
    setKeyboardMode(true);
  }
  if (e.key === "Enter" && swallowEnter) {
    e.preventDefault();
    return;
  }
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
      BACK_KEYS.has(e.key) || BACK_KEY_CODES.has(e.keyCode)
    ) {
      e.preventDefault();
      stopEditing();
      return;
    }
  }

  // a <video> in full screen: OK = play / pause, left / right = -10 s / +10 s
  if (active?.tagName === "VIDEO" && fullscreenElement()?.contains(active)) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (active.paused) active.play()?.catch?.(() => {});
      else active.pause();
      return;
    }
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      active.currentTime = Math.max(0, active.currentTime + (e.key === "ArrowLeft" ? -10 : 10));
      return;
    }
  }

  const dir = DIRECTIONS[e.key];
  // a focused text box that scrolls (dialog text): up / down read it, then leave it at its ends
  if ((dir === "up" || dir === "down") && active?.matches?.(".ui-modal__body")) {
    const max = active.scrollHeight - active.clientHeight;
    const canScroll = dir === "down" ? active.scrollTop < max - 1 : active.scrollTop > 0;
    if (canScroll) {
      e.preventDefault();
      active.scrollBy({ top: (dir === "down" ? 1 : -1) * Math.max(80, active.clientHeight * 0.6), behavior: "smooth" });
      return;
    }
  }
  if (dir) {
    // in a text field, left / right move the cursor, and only leave the field from its ends
    // (an empty field is left right away): otherwise a remote user is stuck in the search box
    if (typing && (dir === "left" || dir === "right") && !atTextEdge(active, dir)) return;
    const list = candidates();
    let next = active ? nearest(active, dir, list) : startingPoint(list);
    if (!next && active && (dir === "left" || dir === "right")) next = wrapInGroup(active, dir, list);
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
    if (!typing && active.matches(CARD_WITH_ACTIONS)) {
      // short press = open the card (on key up), long press = its options sheet
      e.preventDefault();
      if (!enterHold || enterHold.el !== active) {
        const hold = { el: active, held: false };
        hold.timer = setTimeout(() => {
          hold.held = true;
          swallowEnter = true;
          openOptions(active);
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

  // the remote's menu / info key on a card: its options
  if (MENU_KEYS.has(e.key) && active?.matches(CARD_WITH_ACTIONS)) {
    e.preventDefault();
    openOptions(active);
    return;
  }

  if (BACK_KEYS.has(e.key) || BACK_KEY_CODES.has(e.keyCode)) {
    e.preventDefault();
    if (e.repeat) return; // a held key must not go back several pages
    if (closePopup(active)) return;
    else if (typing && active.matches("input:not([type='checkbox']):not([type='radio']), textarea")) {
      active.blur(); // leave the text field first (the arrows continue from it); Back again = back
    } else goBack();
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
  document.addEventListener("fullscreenchange", onFullscreenChange);
  document.addEventListener("webkitfullscreenchange", onFullscreenChange);
  // real mouse movement only (scrolling under a still pointer also fires mousemove, unmoved)
  document.addEventListener("mousemove", (e) => {
    if (keyboardMode && (e.movementX || e.movementY)) setKeyboardMode(false);
  });
  document.addEventListener("mouseover", (e) => {
    pointerOverIframe = e.target?.tagName === "IFRAME";
  });
}
