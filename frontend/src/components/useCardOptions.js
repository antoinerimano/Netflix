// src/components/useCardOptions.js
// A card's options sheet: opened by a right click, a long press on touch screens, the TV remote
// (hold OK / menu key: tv/spatialNavigation.js sends the card a "contextmenu" event) or a "⋯"
// button. Spread `cardProps` on the card; wrap its click with `guardClick` (a long press must
// not also open the title).
import { useRef, useState } from 'react';

const LONG_PRESS_MS = 500;

export default function useCardOptions() {
  const [open, setOpen] = useState(false);
  const press = useRef({ timer: null, x: 0, y: 0, fired: false });

  const cardProps = {
    'data-options': '',
    onContextMenu: (e) => {
      e.preventDefault();
      setOpen(true);
    },
    onPointerDown: (e) => {
      if (e.pointerType !== 'touch') return;
      const p = press.current;
      clearTimeout(p.timer);
      p.fired = false;
      p.x = e.clientX;
      p.y = e.clientY;
      p.timer = setTimeout(() => {
        p.fired = true;
        setOpen(true);
      }, LONG_PRESS_MS);
    },
    onPointerMove: (e) => {
      const p = press.current;
      if (p.timer && Math.hypot(e.clientX - p.x, e.clientY - p.y) > 10) clearTimeout(p.timer); // a scroll
    },
    onPointerUp: () => clearTimeout(press.current.timer),
    onPointerCancel: () => clearTimeout(press.current.timer),
  };

  const guardClick = (fn) => (e) => {
    if (press.current.fired) {
      press.current.fired = false;
      return;
    }
    fn?.(e);
  };

  return { open, setOpen, cardProps, guardClick };
}
