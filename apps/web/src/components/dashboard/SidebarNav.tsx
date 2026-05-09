import type { ReactNode } from 'react';
import logoIcon from '../../assets/logo-icon.svg';

export type AppTab =
  | 'overview'
  | 'activities'
  | 'body'
  | 'nutrition'
  | 'recipes'
  | 'settings';

type Item = {
  id: AppTab;
  label: string;
  icon: ReactNode;
};

const baseSvg = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

const ChartIcon = () => (
  <svg {...baseSvg} aria-hidden>
    <line x1="18" y1="20" x2="18" y2="10" />
    <line x1="12" y1="20" x2="12" y2="4" />
    <line x1="6" y1="20" x2="6" y2="14" />
  </svg>
);
const RunIcon = () => (
  <svg {...baseSvg} aria-hidden>
    <polyline points="5 19 12 5 19 19" />
    <polyline points="14 15 12 11 10 15" />
  </svg>
);
const ScaleIcon = () => (
  <svg {...baseSvg} aria-hidden>
    <rect x="2" y="7" width="20" height="14" rx="3" />
    <line x1="12" y1="11" x2="12" y2="17" />
    <line x1="9" y1="14" x2="15" y2="14" />
  </svg>
);
const FoodIcon = () => (
  <svg {...baseSvg} aria-hidden>
    <path d="M18 8h1a4 4 0 010 8h-1" />
    <path d="M2 8h16v9a4 4 0 01-4 4H6a4 4 0 01-4-4V8z" />
    <line x1="6" y1="1" x2="6" y2="4" />
    <line x1="10" y1="1" x2="10" y2="4" />
    <line x1="14" y1="1" x2="14" y2="4" />
  </svg>
);
const RecipeIcon = () => (
  <svg {...baseSvg} aria-hidden>
    <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
    <line x1="8" y1="7" x2="16" y2="7" />
    <line x1="8" y1="11" x2="13" y2="11" />
  </svg>
);
const SettingsIcon = () => (
  <svg {...baseSvg} aria-hidden>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 008.6 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
  </svg>
);

const ITEMS: Item[] = [
  { id: 'overview', label: 'Dashboard', icon: <ChartIcon /> },
  { id: 'activities', label: 'Aktywności', icon: <RunIcon /> },
  { id: 'body', label: 'Ciało', icon: <ScaleIcon /> },
  { id: 'nutrition', label: 'Odżywianie', icon: <FoodIcon /> },
  { id: 'recipes', label: 'Przepisy AI', icon: <RecipeIcon /> },
  { id: 'settings', label: 'Ustawienia', icon: <SettingsIcon /> },
];

type Props = {
  active: AppTab;
  onSelect: (tab: AppTab) => void;
  userLabel: string;
  onLogout: () => void;
};

export function SidebarNav({ active, onSelect, userLabel, onLogout }: Props) {
  return (
    <aside className="app-sidebar" aria-label="Główne sekcje">
      <div className="app-sidebar-brand">
        <img
          src={logoIcon}
          alt=""
          className="app-sidebar-logo"
          width={36}
          height={36}
        />
        <span className="app-sidebar-brand-text">bodysync</span>
      </div>
      <nav className="app-sidebar-nav">
        {ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`app-sidebar-nav-item ${active === item.id ? 'active' : ''}`}
            onClick={() => onSelect(item.id)}
            aria-current={active === item.id ? 'page' : undefined}
          >
            <span className="app-sidebar-nav-icon">{item.icon}</span>
            <span className="app-sidebar-nav-label">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="app-sidebar-foot">
        <span className="app-sidebar-user" title={userLabel}>
          {userLabel}
        </span>
        <button
          type="button"
          onClick={onLogout}
          className="app-sidebar-logout"
        >
          Wyloguj
        </button>
      </div>
    </aside>
  );
}
