// Taurus landing page: small enhancements on top of a page that works without them.
//  - every "Visit site" link points at <meta name="site-url"> (one place to change the app's address)
//  - TV remote / keyboard: the focus starts on "Visit site"; arrows move between the links
//  - the drifting poster wall, the typing prompt, the top bar on scroll, sections fading in
(function () {
  'use strict';
  var root = document.documentElement;
  root.classList.add('js');

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- The app's address ----------
  var meta = document.querySelector('meta[name="site-url"]');
  var siteUrl = ((meta && meta.content) || '').replace(/\/+$/, '');
  if (siteUrl) {
    document.querySelectorAll('[data-visit]').forEach(function (a) {
      a.href = siteUrl + (a.getAttribute('data-path') || '/');
    });
  }

  // ---------- TV browsers: the larger "10-foot" size ----------
  var TV_UA = /SMART-TV|SmartTV|Tizen|Web0S|webOS|NetCast|BRAVIA|AFT[A-Z]|Android TV|GoogleTV|HbbTV|CrKey|Roku|VIDAA/i;
  if (TV_UA.test(navigator.userAgent || '')) root.classList.add('tv');

  // ---------- Remote / keyboard ----------
  var links = Array.prototype.slice.call(document.querySelectorAll('a[href]'));
  var start = document.querySelector('[data-autofocus]');
  if (start) start.focus({ preventScroll: true });

  // nearest link in the arrow's direction, by position on screen
  function nearest(from, dir) {
    var a = from.getBoundingClientRect();
    var ax = a.left + a.width / 2;
    var ay = a.top + a.height / 2;
    var best = null;
    var bestScore = Infinity;
    links.forEach(function (el) {
      if (el === from || !el.offsetParent) return;
      var b = el.getBoundingClientRect();
      var bx = b.left + b.width / 2;
      var by = b.top + b.height / 2;
      var dx = bx - ax;
      var dy = by - ay;
      var main = dir === 'left' ? -dx : dir === 'right' ? dx : dir === 'up' ? -dy : dy;
      var cross = dir === 'left' || dir === 'right' ? Math.abs(dy) : Math.abs(dx);
      if (main <= 1) return;
      var score = main + cross * 2;
      if (score < bestScore) {
        bestScore = score;
        best = el;
      }
    });
    return best;
  }

  var DIRS = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
  document.addEventListener('keydown', function (e) {
    var dir = DIRS[e.key];
    if (!dir || e.altKey || e.ctrlKey || e.metaKey) return;
    var current = links.indexOf(document.activeElement) >= 0 ? document.activeElement : null;
    var next = current ? nearest(current, dir) : start;
    e.preventDefault();
    if (next) {
      next.focus({ preventScroll: true });
      // the top link sits in the fixed bar: going there doesn't scroll the page away
      var behavior = reduceMotion ? 'auto' : 'smooth';
      // the closing section is the end of the page: show all of it, not just its button
      if (next.closest('.final')) window.scrollTo({ top: document.body.scrollHeight, behavior: behavior });
      else if (!next.closest('.top')) next.scrollIntoView({ block: 'center', behavior: behavior });
    } else if (dir === 'up') {
      window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
    }
  });

  // ---------- The poster wall ----------
  var wall = document.getElementById('wall');
  if (wall) {
    var COLS = 9;
    var TILES = 6;
    var frag = document.createDocumentFragment();
    for (var c = 0; c < COLS; c++) {
      var col = document.createElement('div');
      col.className = 'wall__col' + (c % 2 ? ' is-reverse' : '');
      col.style.setProperty('--speed', 70 + ((c * 13) % 5) * 14 + 's');
      col.style.marginTop = ((c * 37) % 11) * -1.2 + 'rem';
      // the tiles twice: the column loops without a seam
      for (var i = 0; i < TILES * 2; i++) {
        var n = i % TILES;
        var tile = document.createElement('span');
        tile.className = 'tile' + ((c * 5 + n * 3) % 7 === 0 ? ' is-brand' : '');
        // cinematic hues: teal, amber, violet, crimson, steel blue
        var hues = [190, 28, 265, 350, 215, 12, 170];
        tile.style.setProperty('--hue', hues[(c * 3 + n * 2) % hues.length]);
        tile.style.setProperty('--w', 20 + ((c * 7 + n * 11) % 5) * 10 + '%');
        col.appendChild(tile);
      }
      frag.appendChild(col);
    }
    wall.appendChild(frag);
  }

  // ---------- The "Ask" prompt, typing ----------
  var prompt = document.getElementById('prompt');
  var PHRASES = [
    'Something cozy, under two hours',
    'A mind-bending thriller for tonight',
    'Funny, short, nothing sad please',
    'Like Interstellar, but a series',
  ];
  if (prompt) {
    if (reduceMotion) {
      prompt.textContent = PHRASES[0] + '”';
    } else {
      var p = 0;
      var ch = 0;
      var deleting = false;
      var tick = function () {
        var text = PHRASES[p];
        ch += deleting ? -1 : 1;
        prompt.textContent = text.slice(0, ch) + (ch === text.length ? '”' : '');
        var wait = deleting ? 28 : 55 + Math.random() * 60;
        if (!deleting && ch === text.length) {
          deleting = true;
          wait = 2200;
        } else if (deleting && ch === 0) {
          deleting = false;
          p = (p + 1) % PHRASES.length;
          wait = 400;
        }
        setTimeout(tick, wait);
      };
      setTimeout(tick, 1200);
    }
  }

  // ---------- Top bar gets a glass background once scrolled ----------
  var top = document.querySelector('.top');
  var onScroll = function () {
    top.classList.toggle('is-scrolled', window.scrollY > 24);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // ---------- Sections fade in as they come into view ----------
  var targets = document.querySelectorAll('.section-head, .card, .final > *:not(.final__glow)');
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
    );
    targets.forEach(function (el, i) {
      el.classList.add('in-view');
      if (el.classList.contains('card')) el.style.setProperty('--i', i % 5);
      io.observe(el);
    });
  }
  // the remote moving onto a link far down: show it at once, whatever the observer thinks
  document.addEventListener('focusin', function (e) {
    var section = e.target.closest && e.target.closest('.final');
    if (section) section.querySelectorAll('.in-view').forEach(function (el) { el.classList.add('is-visible'); });
  });

  // ---------- Feature cards: a soft light follows the pointer ----------
  document.querySelectorAll('.card').forEach(function (card) {
    card.addEventListener('pointermove', function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty('--mx', e.clientX - r.left + 'px');
      card.style.setProperty('--my', e.clientY - r.top + 'px');
    });
  });

  var year = document.getElementById('year');
  if (year) year.textContent = String(new Date().getFullYear());
})();
