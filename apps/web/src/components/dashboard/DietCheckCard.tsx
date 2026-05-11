import { useEffect, useState } from 'react';
import { ApiError, dietCheckErrorMessage, getProfileTargets, postTdeeRecalc } from '../../api';
import type { DietCheckResult, DietCheckStatus, ProfileTargets } from '../../types';

// Sprint 11.5 PR2 (per ADR-009) — diet check / progress narrative.
// Patrzy na 14d: cel kcal vs realne kcal vs waga. LLM Haiku pisze
// narrację PL (3-5 zdań), deterministic stats jako "Szczegóły" expansion.
// Działa z manualnym kcal_target — nie wymaga TDEE wizard'a.

const STATUS_LABEL: Record<DietCheckStatus, string> = {
  on_track: 'Zgodnie z planem',
  too_fast: 'Za szybko',
  too_slow_or_gain: 'Za wolno albo tycie',
};

function statusTone(status: DietCheckStatus | null): 'positive' | 'negative' | 'neutral' {
  if (status === 'on_track') return 'positive';
  if (status === 'too_fast' || status === 'too_slow_or_gain') return 'negative';
  return 'neutral';
}

function relativeDayDiff(isoDate: string): string {
  const then = new Date(isoDate);
  const today = new Date();
  const diffMs = today.getTime() - then.getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days === 0) return 'dzisiaj';
  if (days === 1) return '1 dzień temu';
  return `${days} dni temu`;
}

export function DietCheckCard() {
  const [targets, setTargets] = useState<ProfileTargets | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [latest, setLatest] = useState<DietCheckResult | null>(null);
  const [toast, setToast] = useState<{ tone: 'success' | 'info' | 'error'; msg: string } | null>(
    null,
  );
  const [showDetails, setShowDetails] = useState(false);

  const loadTargets = async () => {
    try {
      const t = await getProfileTargets();
      setTargets(t);
      setLoadError(null);
    } catch (e) {
      setLoadError(
        e instanceof ApiError
          ? `Błąd ${e.status}: ${e.message}`
          : 'Nie udało się wczytać postępów diety',
      );
    }
  };

  useEffect(() => {
    void loadTargets();
  }, []);

  const handleCheck = async () => {
    setPending(true);
    setToast(null);
    try {
      const result = await postTdeeRecalc();
      setLatest(result);
      if (result.skipped && result.skip_reason) {
        setToast({ tone: 'info', msg: dietCheckErrorMessage(result.skip_reason) });
      } else if (result.narrative_unavailable) {
        setToast({
          tone: 'info',
          msg: 'Narracja LLM chwilowo niedostępna — pokazuję surowe liczby.',
        });
      } else {
        setToast({ tone: 'success', msg: 'Sprawdzono postępy.' });
      }
      await loadTargets();
    } catch (e) {
      setToast({ tone: 'error', msg: dietCheckErrorMessage(e) });
    } finally {
      setPending(false);
    }
  };

  if (loadError && !targets) {
    return (
      <section className="tdee-card" aria-label="Postępy diety">
        <div className="tdee-card-header">
          <h3>Sprawdź postępy diety</h3>
        </div>
        <p className="error">{loadError}</p>
      </section>
    );
  }

  if (!targets) {
    return (
      <section className="tdee-card" aria-label="Postępy diety">
        <div className="tdee-card-header">
          <h3>Sprawdź postępy diety</h3>
        </div>
        <p className="tdee-card-muted">Wczytywanie…</p>
      </section>
    );
  }

  // `latest` (z aktualnego klika) ma priorytet nad `diet_check_last` z DDB.
  const display = latest ?? targets.diet_check_last ?? null;
  const narrative = latest?.narrative ?? targets.diet_check_last?.narrative ?? null;
  const status = display?.status ?? null;
  const tone = statusTone(status);

  return (
    <section className="tdee-card" aria-label="Postępy diety">
      <div className="tdee-card-header">
        <h3>Sprawdź postępy diety</h3>
        <p className="tdee-card-subtitle">
          Patrzy na ostatnie 14 dni: cel kcal vs realne kcal vs waga. LLM dietetyk wystawia
          narrację po polsku.
        </p>
      </div>

      {narrative && <p className="tdee-card-narrative">{narrative}</p>}

      {display && status && (
        <div className="tdee-card-numbers">
          <div className="tdee-card-primary">
            <span className={`tdee-card-delta tdee-card-delta-${tone}`}>
              {STATUS_LABEL[status]}
            </span>
          </div>
          <div className="tdee-card-secondary">
            <button
              type="button"
              className="tdee-card-toggle"
              onClick={() => setShowDetails((v) => !v)}
            >
              {showDetails ? 'Ukryj szczegóły' : 'Szczegóły'}
            </button>
          </div>
        </div>
      )}

      {showDetails && display && !display.skipped && (
        <dl className="tdee-card-details">
          <div>
            <dt>Cel kcal/dzień</dt>
            <dd>{display.goal_kcal}</dd>
          </div>
          <div>
            <dt>Średnio zjedzone (14d)</dt>
            <dd>{display.kcal_in_avg}</dd>
          </div>
          <div>
            <dt>Waga 14d temu → dziś</dt>
            <dd>
              {(display as DietCheckResult).waga_then_kg ?? '—'} →{' '}
              {(display as DietCheckResult).waga_now_kg ?? '—'} kg ({display.waga_delta_kg ?? 0} kg)
            </dd>
          </div>
          <div>
            <dt>Przewidywana zmiana</dt>
            <dd>{(display as DietCheckResult).expected_delta_kg ?? '—'} kg</dd>
          </div>
          <div>
            <dt>Różnica vs przewidywanie</dt>
            <dd>{display.diff_kg ?? '—'} kg</dd>
          </div>
        </dl>
      )}

      {display && 'date' in display && display.date && (
        <p className="tdee-card-meta">
          Ostatnio sprawdzone: <strong>{relativeDayDiff(String(display.date))}</strong>
        </p>
      )}

      {!display && <p className="tdee-card-muted">Jeszcze nie sprawdzone — kliknij poniżej.</p>}

      <div className="tdee-card-actions">
        {toast && (
          <span className={`tdee-card-toast tdee-card-toast-${toast.tone}`}>{toast.msg}</span>
        )}
        <button
          type="button"
          className="tdee-card-button"
          onClick={handleCheck}
          disabled={pending}
        >
          {pending ? 'Sprawdzam…' : 'Sprawdź teraz'}
        </button>
      </div>
    </section>
  );
}
