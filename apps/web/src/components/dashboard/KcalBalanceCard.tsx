import { buildSeries, sumSeries, valueForDate } from '../../biometry';
import type { BiometryDay } from '../../types';

type Props = {
  days: BiometryDay[];
  todayIso: string; // YYYY-MM-DD w boundary Warsaw — pobierane z parenta
};

type BalanceDay = {
  date: string;
  balance: number; // kcal_in - kcal_burned. Negative = deficyt, positive = nadwyżka
};

// Próg "bilans" — różnica poniżej 100 kcal w obie strony traktujemy jako
// neutralny bilans. Real-life HAE dane mają ±50-100 kcal noise z auto-detect
// activity, więc tight zero threshold dawałby fałszywe alarmy.
const BALANCE_THRESHOLD = 100;

type Status = 'deficyt' | 'nadwyzka' | 'bilans';

function statusOf(balance: number): Status {
  if (balance < -BALANCE_THRESHOLD) return 'deficyt';
  if (balance > BALANCE_THRESHOLD) return 'nadwyzka';
  return 'bilans';
}

const STATUS_LABEL: Record<Status, string> = {
  deficyt: 'DEFICYT',
  nadwyzka: 'NADWYŻKA',
  bilans: 'BILANS',
};

const integerFmt = (v: number) => Math.round(v).toLocaleString('pl-PL');

// Format balance number z explicit +/- sign. 0 → "0".
function formatBalance(v: number): string {
  if (v === 0) return '0';
  const rounded = Math.round(v);
  return rounded > 0 ? `+${integerFmt(rounded)}` : `−${integerFmt(Math.abs(rounded))}`;
}

// Snapshot Bilans kaloryczny — today's kcal_in vs kcal_burned + 7-day
// sparkline (mini per-day bars). Empty state gdy ani today's in ani burned
// nie są zarejestrowane (HAE nie wysłał, manual kcal_in nie wpisany).
export function KcalBalanceCard({ days, todayIso }: Props) {
  const kcalInSeries = buildSeries(days, 'kcal_in');
  const kcalActiveSeries = buildSeries(days, 'kcal_active');
  const kcalBasalSeries = buildSeries(days, 'kcal_basal');
  const kcalBurnedSeries = sumSeries(kcalActiveSeries, kcalBasalSeries);

  const todayIn = valueForDate(kcalInSeries, todayIso)?.value ?? null;
  const todayBurned = valueForDate(kcalBurnedSeries, todayIso)?.value ?? null;

  // Build 7-day balance array (oldest → newest). Brakujące dni pomijamy.
  const balanceByDate = new Map<string, number>();
  const allDates = new Set([
    ...kcalInSeries.map((p) => p.date),
    ...kcalBurnedSeries.map((p) => p.date),
  ]);
  for (const date of allDates) {
    const inVal = valueForDate(kcalInSeries, date)?.value;
    const burnedVal = valueForDate(kcalBurnedSeries, date)?.value;
    // Wymagamy obu metryk żeby balance miał sens (in bez burned = MISLEADING).
    if (inVal !== undefined && burnedVal !== undefined) {
      balanceByDate.set(date, inVal - burnedVal);
    }
  }
  const last7d: BalanceDay[] = [...balanceByDate.entries()]
    .map(([date, balance]) => ({ date, balance }))
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-7);

  // Empty state gdy żadnego dnia nie mamy obu metryk
  if (todayIn === null && todayBurned === null && last7d.length === 0) {
    return (
      <section className="kcal-balance-card kcal-balance-card-empty" aria-label="Bilans kaloryczny">
        <h3>Bilans kaloryczny</h3>
        <p>
          Brak danych — wpisz kcal spożyte w Odżywianiu i upewnij się że HAE wysyła energy
          burned (active + basal).
        </p>
      </section>
    );
  }

  const todayBalance =
    todayIn !== null && todayBurned !== null ? todayIn - todayBurned : null;
  const status = todayBalance !== null ? statusOf(todayBalance) : null;

  // Max abs value w 7-day window dla normalizacji sparkline height.
  const maxAbs = Math.max(1, ...last7d.map((d) => Math.abs(d.balance)));

  return (
    <section className="kcal-balance-card" aria-label="Bilans kaloryczny">
      <h3>Bilans kaloryczny</h3>

      {todayBalance !== null ? (
        <div className="kcal-balance-primary">
          <span className={`kcal-balance-value kcal-balance-${status}`}>
            {formatBalance(todayBalance)}
            <span className="kcal-balance-unit"> kcal</span>
          </span>
          {status && (
            <span className={`kcal-balance-status kcal-balance-${status}`}>
              {STATUS_LABEL[status]}
            </span>
          )}
        </div>
      ) : (
        <div className="kcal-balance-primary">
          <span className="kcal-balance-value kcal-balance-empty-today">—</span>
          <span className="kcal-balance-status kcal-balance-empty-today">
            BRAK DZISIEJSZYCH DANYCH
          </span>
        </div>
      )}

      <div className="kcal-balance-breakdown">
        <div>
          <span className="kcal-balance-breakdown-label">Spożyte</span>
          <span className="kcal-balance-breakdown-value">
            {todayIn !== null ? integerFmt(todayIn) : '—'} <small>kcal</small>
          </span>
        </div>
        <div>
          <span className="kcal-balance-breakdown-label">Spalone</span>
          <span className="kcal-balance-breakdown-value">
            {todayBurned !== null ? integerFmt(todayBurned) : '—'} <small>kcal</small>
          </span>
        </div>
      </div>

      {last7d.length > 0 && (
        <div className="kcal-balance-spark">
          <span className="kcal-balance-spark-label">Ost. 7 dni:</span>
          <div className="kcal-balance-spark-bars" role="img" aria-label="Bilans kcal ostatnich 7 dni">
            {last7d.map((d) => {
              const heightPct = (Math.abs(d.balance) / maxAbs) * 100;
              const dayStatus = statusOf(d.balance);
              return (
                <span
                  key={d.date}
                  className={`kcal-balance-spark-bar kcal-balance-${dayStatus}`}
                  style={{ height: `${Math.max(heightPct, 8)}%` }}
                  title={`${d.date}: ${formatBalance(d.balance)} kcal`}
                />
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
