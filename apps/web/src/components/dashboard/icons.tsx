// Inline SVG ikonki dla StatCard. Stroke "currentColor" — kolor dziedziczy
// po `.stat-card-icon` CSS (per-accent class). 18×18 viewBox=24 — drobny
// detail, nie dominuje karty.
//
// Style ref: prototype Icons (np. linie 75-156 health-dashboard-prototype.jsx),
// adaptowane: Lucide-style stroke 2 round.

import type { SVGProps } from 'react';

const baseProps: SVGProps<SVGSVGElement> = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
};

export const FlameIcon = () => (
  <svg {...baseProps}>
    <path d="M12 12c2-2.96 0-7-1-8 0 3.038-1.773 4.741-3 6-1.226 1.26-2 3.24-2 5a6 6 0 1012 0c0-1.532-1.056-3.94-2-5-1.786 3-2.791 3-4 2z" />
  </svg>
);

// Run/Activity (chevron up) — Strava-vibe, używane w "Aktywności tygodnia"
// StatCard. Mirror RunIcon w SidebarNav (sidebar nav używa swojej wewnętrznej
// kopii; tutaj export żeby StatCard mógł reużyć).
export const RunIcon = () => (
  <svg {...baseProps}>
    <polyline points="5 19 12 5 19 19" />
    <polyline points="14 15 12 11 10 15" />
  </svg>
);

export const FootprintsIcon = () => (
  <svg {...baseProps}>
    <path d="M4 16v-2a3 3 0 116 0v2a3 3 0 01-6 0z" />
    <path d="M4 22h6" />
    <path d="M14 8V6a3 3 0 116 0v2a3 3 0 01-6 0z" />
    <path d="M14 14h6" />
  </svg>
);

export const HeartPulseIcon = () => (
  <svg {...baseProps}>
    <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 000-7.78z" />
    <path d="M3.22 12h4l1.5-3 3 6 1.5-3h7.56" />
  </svg>
);

export const HeartIcon = () => (
  <svg {...baseProps}>
    <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" />
  </svg>
);

export const MoonIcon = () => (
  <svg {...baseProps}>
    <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
  </svg>
);

export const ScaleIcon = () => (
  <svg {...baseProps}>
    <path d="M16 16.5a4 4 0 008 0l-4-9-4 9z" />
    <path d="M0 16.5a4 4 0 008 0l-4-9-4 9z" />
    <path d="M7 21h10" />
    <path d="M12 3v18" />
    <path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2" />
  </svg>
);

export const UtensilsIcon = () => (
  <svg {...baseProps}>
    <path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 002-2V2" />
    <path d="M7 2v20" />
    <path d="M21 15V2a5 5 0 00-5 5v6c0 1.1.9 2 2 2h3zm0 0v7" />
  </svg>
);

export const EggIcon = () => (
  <svg {...baseProps}>
    <path d="M12 22c-4.97 0-9-3.582-9-8 0-5.523 4.03-12 9-12s9 6.477 9 12c0 4.418-4.03 8-9 8z" />
  </svg>
);

export const DropletIcon = () => (
  <svg {...baseProps}>
    <path d="M12 2.69l5.66 5.66a8 8 0 11-11.31 0z" />
  </svg>
);

export const WheatIcon = () => (
  <svg {...baseProps}>
    <path d="M2 22l10-10" />
    <path d="M16 8 A4 4 0 0 0 20 4 A4 4 0 0 0 16 8 Z" />
    <path d="M17.5 13 A4 4 0 0 0 21.5 9 A4 4 0 0 0 17.5 13 Z" />
    <path d="M19 18 A4 4 0 0 0 23 14 A4 4 0 0 0 19 18 Z" />
    <path d="M11 13 A4 4 0 0 0 15 9 A4 4 0 0 0 11 13 Z" />
    <path d="M12.5 18 A4 4 0 0 0 16.5 14 A4 4 0 0 0 12.5 18 Z" />
    <path d="M9 23 A4 4 0 0 0 13 19 A4 4 0 0 0 9 23 Z" />
  </svg>
);

export const PercentIcon = () => (
  <svg {...baseProps}>
    <line x1="19" y1="5" x2="5" y2="19" />
    <circle cx="6.5" cy="6.5" r="2.5" />
    <circle cx="17.5" cy="17.5" r="2.5" />
  </svg>
);
