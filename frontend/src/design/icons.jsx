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
    {/* optically centered: the box spans x 6-20, the heavier left side sits a bit left of 12 */}
    <path d="M6 4.6v14.8a1 1 0 0 0 1.52.85l12-7.4a1 1 0 0 0 0-1.7l-12-7.4A1 1 0 0 0 6 4.6Z" />
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
export const ListPlusIcon = (p) => (
  <Icon {...p}>
    <path d="M4 6h11M4 12h11M4 18h7M18 14v6M15 17h6" />
  </Icon>
);
export const CalendarIcon = (p) => (
  <Icon {...p}>
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </Icon>
);
export const BellOffIcon = (p) => (
  <Icon {...p}>
    <path d="M8.5 4.1A6 6 0 0 1 18 9c0 3 .6 4.9 1.2 6M17 16.5H3.5S6 15 6 9c0-.6.1-1.2.3-1.8" />
    <path d="M10 20a2.2 2.2 0 0 0 4 0M3 3l18 18" />
  </Icon>
);
// arrows that point along the reading direction: mirrored in right-to-left languages
const flip = (p) => ({ ...p, className: ["ui-icon--flip", p.className].filter(Boolean).join(" ") });
export const ArrowLeftIcon = (p) => (
  <Icon {...flip(p)}>
    <path d="M19 12H5M11 18l-6-6 6-6" />
  </Icon>
);
export const ChevronLeftIcon = (p) => (
  <Icon {...flip(p)}>
    <path d="m15 6-6 6 6 6" />
  </Icon>
);
export const ChevronRightIcon = (p) => (
  <Icon {...flip(p)}>
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
export const VolumeOnIcon = (p) => (
  <Icon {...p}>
    <path d="M11 5 6 9H3v6h3l5 4V5Z" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
  </Icon>
);
export const VolumeOffIcon = (p) => (
  <Icon {...p}>
    <path d="M11 5 6 9H3v6h3l5 4V5Z" />
    <path d="m16 9 6 6M22 9l-6 6" />
  </Icon>
);
export const BanIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="m5.6 5.6 12.8 12.8" />
  </Icon>
);
export const HomeIcon = (p) => (
  <Icon {...p}>
    <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1v-9.5Z" />
  </Icon>
);
export const TvIcon = (p) => (
  <Icon {...p}>
    <rect x="2.5" y="5" width="19" height="13" rx="2" />
    <path d="M8 21h8M8 2l4 3 4-3" />
  </Icon>
);
export const BookmarkIcon = (p) => (
  <Icon {...p}>
    <path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4.5L5 21V4a1 1 0 0 1 1-1Z" />
  </Icon>
);
export const ShareIcon = (p) => (
  <Icon {...p}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4" />
  </Icon>
);
export const MoreIcon = (p) => (
  <Icon filled {...p}>
    <circle cx="5" cy="12" r="2" />
    <circle cx="12" cy="12" r="2" />
    <circle cx="19" cy="12" r="2" />
  </Icon>
);
export const MaximizeIcon = (p) => (
  <Icon {...p}>
    <path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4" />
  </Icon>
);
export const LinkIcon = (p) => (
  <Icon {...p}>
    <path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1" />
    <path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1" />
  </Icon>
);
export const DiceIcon = (p) => (
  <Icon {...p}>
    <rect x="3.5" y="3.5" width="17" height="17" rx="4" />
    <circle cx="8.5" cy="8.5" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="15.5" cy="15.5" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="15.5" cy="8.5" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="8.5" cy="15.5" r="1.2" fill="currentColor" stroke="none" />
  </Icon>
);
export const WandIcon = (p) => (
  <Icon {...p}>
    <path d="m4 20 12-12M14 6l4 4" />
    <path d="M18 2v3M16.5 3.5h3M21 8v2M20 9h2M9 3v2M8 4h2" />
  </Icon>
);
export const EyeIcon = (p) => (
  <Icon {...p}>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
    <circle cx="12" cy="12" r="3" />
  </Icon>
);
export const EyeOffIcon = (p) => (
  <Icon {...p}>
    <path d="M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.6 3.4M6.6 6.6C3.9 8.3 2.5 12 2.5 12S6 18.5 12 18.5c1.9 0 3.5-.6 4.9-1.5" />
    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" />
  </Icon>
);
export const MailIcon = (p) => (
  <Icon {...p}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="m3.5 6.5 8.5 6.5 8.5-6.5" />
  </Icon>
);

export const GlobeIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18" />
    <path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18Z" />
  </Icon>
);
