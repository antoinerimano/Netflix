// TV remote navigation (spatialNavigation.js). jsdom has no layout: each element gets a box.
import { startSpatialNavigation } from './spatialNavigation';

const boxes = new WeakMap();
const realRect = Element.prototype.getBoundingClientRect;

function place(el, x, y, w = 100, h = 50) {
  boxes.set(el, { x, y, w, h });
  return el;
}

function key(name) {
  const e = new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true });
  window.dispatchEvent(e);
  return e;
}

function add(html) {
  const wrap = document.createElement('div');
  wrap.innerHTML = html.trim();
  const el = wrap.firstElementChild;
  document.body.appendChild(el);
  return el;
}

beforeAll(() => {
  Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
    const b = boxes.get(this) || { x: 0, y: 0, w: 0, h: 0 };
    return { left: b.x, top: b.y, width: b.w, height: b.h, right: b.x + b.w, bottom: b.y + b.h, x: b.x, y: b.y };
  };
  window.scrollBy = jest.fn();
  window.innerWidth = 1920;
  window.innerHeight = 1080;
  startSpatialNavigation();
});

afterAll(() => {
  Element.prototype.getBoundingClientRect = realRect;
});

beforeEach(() => {
  document.body.innerHTML = '';
});

test('arrows move to the nearest element in that direction', () => {
  const a = place(add('<button>A</button>'), 100, 200);
  const b = place(add('<button>B</button>'), 100, 400);
  const c = place(add('<button>C</button>'), 400, 400);
  a.focus();
  key('ArrowDown');
  expect(document.activeElement).toBe(b);
  key('ArrowRight');
  expect(document.activeElement).toBe(c);
  key('ArrowUp');
  expect(document.activeElement).toBe(a); // the only thing above
});

test('the first arrow starts on the page main action that is on screen', () => {
  place(add('<button class="ui-btn--primary">Off screen</button>'), 100, -500);
  const onScreen = place(add('<button class="ui-btn--primary">Play</button>'), 100, 300);
  place(add('<button>Other</button>'), 100, 600);
  document.activeElement.blur();
  key('ArrowDown');
  expect(document.activeElement).toBe(onScreen);
});

test('up from the page reaches the banner before the fixed navbar', () => {
  const nav = add('<nav class="navbar"><a href="/search">Search</a></nav>');
  const searchLink = place(nav.querySelector('a'), 1300, 10, 200, 40);
  place(nav, 0, 0, 1920, 60);
  const play = place(add('<button>Play</button>'), 60, 500, 130, 50);
  const card = place(add('<div tabindex="0" class="movie-card">Card</div>'), 1300, 700, 280, 160);
  card.focus();
  key('ArrowUp');
  expect(document.activeElement).toBe(play);
  key('ArrowUp');
  expect(document.activeElement).toBe(searchLink); // nothing left above in the page
});

test('up / down ignore an element on the same line', () => {
  const nav = add('<nav class="navbar"><a href="/">Home</a></nav>');
  const home = place(nav.querySelector('a'), 60, 10);
  const moreInfo = place(add('<button>More info</button>'), 200, 496, 150, 52);
  const sound = place(add('<button>Sound</button>'), 1400, 500, 44, 44);
  sound.focus();
  key('ArrowUp');
  expect(document.activeElement).not.toBe(moreInfo);
  expect(document.activeElement).toBe(home);
});

test('a closed select never changes its value with the arrows', () => {
  const select = place(add('<select><option value="en">EN</option><option value="fr">FR</option></select>'), 100, 900);
  select.focus();
  const e = key('ArrowDown'); // nothing below: the browser would pick the next option
  expect(e.defaultPrevented).toBe(true);
  expect(select.value).toBe('en');
});

test('the focus continues next to an element that went away', () => {
  const left = place(add('<button>Left</button>'), 100, 300);
  const gone = place(add('<button>Gone</button>'), 400, 300);
  const right = place(add('<button>Right</button>'), 700, 300);
  gone.focus();
  gone.remove(); // e.g. a button shown only while a trailer plays
  key('ArrowRight');
  expect([left, right]).toContain(document.activeElement);
});

test('an open dialog keeps the remote inside it', () => {
  const page = place(add('<button>Page</button>'), 100, 100);
  const modal = place(add('<div class="ui-modal"><button>One</button><button>Two</button></div>'), 0, 0, 1920, 1080);
  const [one, two] = modal.querySelectorAll('button');
  place(one, 800, 400);
  place(two, 800, 500);
  one.focus();
  key('ArrowDown');
  expect(document.activeElement).toBe(two);
  key('ArrowDown');
  key('ArrowUp');
  key('ArrowUp');
  expect(document.activeElement).not.toBe(page);
});
