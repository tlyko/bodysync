// Pure helpers dla ActivityList — sport icon, format duration/distance/pace.

const SPORT_ICONS: Record<string, string> = {
  Run: '🏃',
  TrailRun: '🏃',
  VirtualRun: '🏃',
  Ride: '🚴',
  VirtualRide: '🚴',
  GravelRide: '🚴',
  MountainBikeRide: '🚵',
  EBikeRide: '🚴',
  EMountainBikeRide: '🚵',
  Walk: '🚶',
  Hike: '🥾',
  Swim: '🏊',
  WeightTraining: '🏋️',
  Workout: '💪',
  Yoga: '🧘',
  Crossfit: '🤸',
  Rowing: '🚣',
  Kayaking: '🛶',
  Skating: '⛸️',
  AlpineSki: '⛷️',
  BackcountrySki: '⛷️',
  NordicSki: '🎿',
  Snowboard: '🏂',
  Surfing: '🏄',
  Climbing: '🧗',
  RockClimbing: '🧗',
  Soccer: '⚽',
  Tennis: '🎾',
  Golf: '⛳',
  Elliptical: '🏃',
  StairStepper: '🪜',
  HighIntensityIntervalTraining: '🔥',
};

export function sportIcon(sport: string): string {
  return SPORT_ICONS[sport] ?? '⚡';
}

const SPORT_LABELS: Record<string, string> = {
  Run: 'Bieg',
  TrailRun: 'Bieg w terenie',
  VirtualRun: 'Bieg wirtualny',
  Ride: 'Rower',
  VirtualRide: 'Rower wirtualny',
  GravelRide: 'Gravel',
  MountainBikeRide: 'MTB',
  EBikeRide: 'eBike',
  Walk: 'Spacer',
  Hike: 'Szlak',
  Swim: 'Pływanie',
  WeightTraining: 'Siłownia',
  Workout: 'Trening',
  Yoga: 'Joga',
  Crossfit: 'Crossfit',
  Rowing: 'Wioślarstwo',
  Climbing: 'Wspinaczka',
  RockClimbing: 'Wspinaczka',
};

export function sportLabel(sport: string): string {
  return SPORT_LABELS[sport] ?? sport;
}

export function formatDistance(distanceMeters: number): string {
  if (distanceMeters >= 1000) {
    return `${(distanceMeters / 1000).toFixed(2)} km`;
  }
  return `${Math.round(distanceMeters)} m`;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatPace(distanceMeters: number, movingSeconds: number): string | null {
  if (distanceMeters < 100 || movingSeconds < 10) return null;
  const minPerKm = movingSeconds / 60 / (distanceMeters / 1000);
  const m = Math.floor(minPerKm);
  const s = Math.round((minPerKm - m) * 60);
  return `${m}:${String(s).padStart(2, '0')} /km`;
}

// Lokalna data względem `now`. "Dziś", "Wczoraj", "5 dni temu", "8 maja",
// "8 maja 2025" jeśli z innego roku.
export function formatRelativeDate(isoLocal: string, now: Date = new Date()): string {
  // start_date_local jest "YYYY-MM-DDTHH:MM:SS" bez timezone — traktujemy jako local clock.
  const date = new Date(isoLocal);
  if (isNaN(date.getTime())) return isoLocal;

  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.floor((startOfDay(now) - startOfDay(date)) / 86400000);

  if (diffDays === 0) return 'Dziś';
  if (diffDays === 1) return 'Wczoraj';
  if (diffDays > 1 && diffDays < 7) return `${diffDays} dni temu`;

  const fmt = new Intl.DateTimeFormat('pl-PL', {
    day: 'numeric',
    month: 'long',
    ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
  });
  return fmt.format(date);
}
