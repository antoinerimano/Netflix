// src/design/icons.js
// One icon set for the app (24 px grid, 2 px strokes, currentColor), replacing emoji and
// one-off inline SVGs: emoji render differently on every OS / TV and can't take the text color.
import React from "react";

function Icon({ children, filled = false, ...props }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

export const PlayIcon = (p) => (
  <Icon filled {...p}>
    <path d="M7 4.6v14.8a1 1 0 0 0 1.52.85l12-7.4a1 1 0 0 0 0-1.7l-12-7.4A1 1 0 0 0 7 4.6Z" />
  </Icon>
);
export const PauseIcon = (p) => (
  <Icon filled {...p}>
    <rect x="6" y="4" width="4" height="16" rx="1" />
    <rect x="14" y="4" width="4" height="16" rx="1" />
  </Icon>
);
export const PlusIcon = (p) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);
export const CheckIcon = (p) => (
  <Icon {...p}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Icon>
);
export const CloseIcon = (p) => (
  <Icon {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icon>
);
export const InfoIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 7.5v.01" />
  </Icon>
);
export const ThumbUpIcon = (p) => (
  <Icon {...p}>
    <path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h3Z" />
    <path d="M7 10l4-7a2.5 2.5 0 0 1 2.5 2.9L13 10h5.6a2 2 0 0 1 2 2.4l-1.5 7A2 2 0 0 1 17.1 21H7" />
  </Icon>
);
export const ThumbDownIcon = (p) => (
  <Icon {...p}>
    <path d="M17 14V3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-3Z" />
    <path d="M17 14l-4 7a2.5 2.5 0 0 1-2.5-2.9L11 14H5.4a2 2 0 0 1-2-2.4l1.5-7A2 2 0 0 1 6.9 3H17" />
  </Icon>
);
export const BellIcon = (p) => (
  <Icon {...p}>
    <path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9Z" />
    <path d="M10 20a2.2 2.2 0 0 0 4 0" />
  </Icon>
);
export const BellOffIcon = (p) => (
  <Icon {...p}>
    <path d="M8.5 4.1A6 6 0 0 1 18 9c0 3 .6 4.9 1.2 6M17 16.5H3.5S6 15 6 9c0-.6.1-1.2.3-1.8" />
    <path d="M10 20a2.2 2.2 0 0 0 4 0M3 3l18 18" />
  </Icon>
);
export const ArrowLeftIcon = (p) => (
  <Icon {...p}>
    <path d="M19 12H5M11 18l-6-6 6-6" />
  </Icon>
);
export const ChevronRightIcon = (p) => (
  <Icon {...p}>
    <path d="m9 6 6 6-6 6" />
  </Icon>
);
export const SearchIcon = (p) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Icon>
);
export const FilmIcon = (p) => (
  <Icon {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" />
  </Icon>
);
export const AlertIcon = (p) => (
  <Icon {...p}>
    <path d="M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17v.01" />
  </Icon>
);
export const StarIcon = (p) => (
  <Icon filled {...p}>
    <path d="m12 2.8 2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3-4.6-4.4 6.3-.9L12 2.8Z" />
  </Icon>
);
