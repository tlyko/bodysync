import { useEffect, useState } from 'react';
import { ApiError, getProfileTargets, postTdeeRecalc, tdeeRecalcErrorMessage } from '../../api';
import type { ProfileTargets, RecalcResult } from '../../types';

// Sprint 11 PR5 — adaptive TDEE display + manual "Przelicz teraz" button.
// Sekcja w Settings tab pod ProfileTargetsForm. Pokazuje current tdee_adaptive
// vs tdee_baseline + delta badge (kolor zależny od kierunku zmiany).
// Manual recalc dla testowania/forsowania przed automatycznym 14d cron.

function relativeDayDiff(isoDate: string): string {
  const then = new Date(isoDate);
  const today = new Date();
  const diffMs = today.getTime() - then.getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days === 0) return 'dzisiaj';
  if (days === 1) return '1 dzień temu';
  if (days < 5) return `${days} dni temu`;
  return `${days} dni temu`;
}

function deltaTone(delta: number): 'positive' | 'negative' | 'neutral' {
  if (delta > 0) return 'positive';
  if (delta < 0) return 'negative';
  return 'neutral';
}

export function TDEEAdaptiveCard() {
  const [targets, setTargets] = useState<ProfileTargets | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [toast, setToast] = useState<{ tone: 'success' | 'info' | 'error'; msg: string } | null>(
    null,
  );

  const loadTargets = async () => {
    try {
      const t = await getProfileTargets();
      setTargets(t);
      setLoadError(null);
    } catch (e) {
      setLoadError(
        e instanceof ApiError ? `Błąd ${e.status}: ${e.message}` : 'Nie udało się wczytać TDEE',
      );
    }
  };

  useEffect(() => {
    void loadTargets();
  }, []);

  const handleRecalc = async () => {
    setPending(true);
    setToast(null);
    try {
      const result: RecalcResult = await postTdeeRecalc();
      if (result.skipped && result.reason) {
        setToast({ tone: 'info', msg: tdeeRecalcErrorMessage(result.reason) });
      } else {
        const delta = (result.tdee_after ?? 0) - (result.tdee_before ?? 0);
        const sign = delta > 0 ? '+' : '';
        setToast({
          tone: 'success',
          msg: `TDEE zaktualizowane: ${result.tdee_after} kcal (${sign}${delta} vs poprzednie).`,
        });
      }
      await loadTargets();
    } catch (e) {
      setToast({ tone: 'error', msg: tdeeRecalcErrorMessage(e) });
    } finally {
      setPending(false);
    }
  };

  if (loadError && !targets) {
    return (
      <section className="tdee-card" aria-label="TDEE adaptacyjne">
        <div className="tdee-card-header">
          <h3>TDEE adaptacyjne</h3>
        </div>
        <p className="error">{loadError}</p>
      </section>
    );
  }

  if (!targets) {
    return (
      <section className="tdee-card" aria-label="TDEE adaptacyjne">
        <div className="tdee-card-header">
          <h3>TDEE adaptacyjne</h3>
        </div>
        <p className="tdee-card-muted">Wczytywanie…</p>
      </section>
    );
  }

  const baseline = targets.tdee_baseline ?? null;
  const adaptive = targets.tdee_adaptive ?? null;
  const lastRecalc = targets.tdee_last_recalc ?? null;
  const initialized = baseline !== null && adaptive !== null;
  const delta = initialized ? adaptive - baseline : 0;
  const tone = deltaTone(delta);

  return (
    <section className="tdee-card" aria-label="TDEE adaptacyjne">
      <div className="tdee-card-header">
        <h3>TDEE adaptacyjne</h3>
        <p className="tdee-card-subtitle">
          Auto-korekta TDEE co 14 dni na bazie waga + kcal_in. MacroFactor-style.
        </p>
      </div>

      {!initialized && (
        <div className="tdee-card-banner">
          Najpierw uzupełnij swój profil ciała powyżej (przycisk „Oblicz mój TDEE"). Dopiero
          wtedy adaptacyjne TDEE może działać.
        </div>
      )}

      {initialized && (
        <>
          <div className="tdee-card-numbers">
            <div className="tdee-card-primary">
              <span className="tdee-card-value">{adaptive}</span>
              <span className="tdee-card-unit">kcal/dzień</span>
            </div>
            <div className="tdee-card-secondary">
              <span className="tdee-card-baseline">baseline {baseline}</span>
              <span
                className={`tdee-card-delta tdee-card-delta-${tone}`}
                aria-label={`Różnica vs baseline ${delta} kcal`}
              >
                {delta > 0 ? `+${delta}` : delta}
              </span>
            </div>
          </div>

          <p className="tdee-card-meta">
            {lastRecalc ? (
              <>
                Ostatnio zaktualizowane: <strong>{relativeDayDiff(lastRecalc.date)}</strong>
                {lastRecalc.event === 'skipped' && lastRecalc.reason && (
                  <>
                    {' '}
                    (skip: {tdeeRecalcErrorMessage(lastRecalc.reason as never)})
                  </>
                )}
              </>
            ) : (
              <>Jeszcze nie obliczone — kliknij poniżej.</>
            )}
          </p>
        </>
      )}

      <div className="tdee-card-actions">
        {toast && (
          <span className={`tdee-card-toast tdee-card-toast-${toast.tone}`}>{toast.msg}</span>
        )}
        <button
          type="button"
          className="tdee-card-button"
          onClick={handleRecalc}
          disabled={pending}
        >
          {pending ? 'Przeliczam…' : 'Przelicz teraz'}
        </button>
      </div>
    </section>
  );
}
