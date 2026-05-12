import { useState, type FormEvent } from 'react';
import { postWaitlist, waitlistErrorMessage } from '../api';

// PR2 waitlist landing — public form na LoginScreen. Zbiera email + opcjonalny
// "czego oczekujesz" tekst + RODO consent. Honeypot field `phone` (CSS off-screen,
// NIE display:none — niektóre boty skipują display:none) wysyłany ZAWSZE; bot
// wypełni, legit user zostawi pusty. Backend rozpoznaje i zwraca 200 silently
// (bot signal, NIE 422 — żeby nie uczyć bota co poszło źle).

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const INTEREST_MAX = 500;

type SubmitState = 'idle' | 'submitting' | 'success' | 'error';

type FieldErrors = {
  email?: string;
  consent?: string;
};

export function WaitlistForm() {
  const [email, setEmail] = useState('');
  const [interest, setInterest] = useState('');
  const [consent, setConsent] = useState(false);
  // Honeypot — kontrolowane state mimo że user go nie widzi. Bot wypełnia,
  // wysyłamy z payload, backend zwraca 200 silent. Empty string z legit usera.
  const [honeypot, setHoneypot] = useState('');
  const [state, setState] = useState<SubmitState>('idle');
  const [serverError, setServerError] = useState<string>('');
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  const canSubmit = email.trim().length > 0 && consent && state !== 'submitting';

  const validate = (): FieldErrors => {
    const errors: FieldErrors = {};
    if (!EMAIL_REGEX.test(email.trim())) {
      errors.email = 'Wpisz prawidłowy adres email.';
    }
    if (!consent) {
      errors.consent = 'Wymagana zgoda na przetwarzanie danych.';
    }
    return errors;
  };

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      return;
    }
    setState('submitting');
    setServerError('');
    try {
      await postWaitlist({
        email: email.trim(),
        consent,
        honeypot,
        interest: interest.trim().length > 0 ? interest.trim() : null,
      });
      setState('success');
    } catch (err) {
      setServerError(waitlistErrorMessage(err));
      setState('error');
    }
  };

  if (state === 'success') {
    return (
      <div className="waitlist-success" role="status" aria-live="polite">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 12l5 5L20 7" />
        </svg>
        <p>Dzięki! Odezwę się gdy ruszymy szerzej.</p>
      </div>
    );
  }

  return (
    <form className="waitlist-form" onSubmit={onSubmit} noValidate>
      <div>
        <label htmlFor="waitlist-email">Adres email</label>
        <input
          id="waitlist-email"
          type="email"
          required
          aria-required="true"
          aria-invalid={fieldErrors.email ? 'true' : undefined}
          aria-describedby={fieldErrors.email ? 'waitlist-email-error' : undefined}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          placeholder="ty@example.com"
        />
        {fieldErrors.email && (
          <p id="waitlist-email-error" className="waitlist-field-error" role="alert">
            {fieldErrors.email}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="waitlist-interest">Czego najbardziej oczekujesz? (opcjonalnie)</label>
        <textarea
          id="waitlist-interest"
          value={interest}
          onChange={(e) => setInterest(e.target.value.slice(0, INTEREST_MAX))}
          maxLength={INTEREST_MAX}
          placeholder="np. spersonalizowane plany żywieniowe, predykcje regeneracji, pomoc w deficycie..."
        />
        <div className="waitlist-counter" aria-hidden="true">
          {interest.length}/{INTEREST_MAX}
        </div>
      </div>

      {/* Honeypot — hidden off-screen via CSS (NIE display:none). aria-hidden
          + tabIndex=-1 żeby screen readery i Tab-nav go skipowały. */}
      <input
        type="text"
        name="phone"
        className="waitlist-honeypot"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={honeypot}
        onChange={(e) => setHoneypot(e.target.value)}
      />

      <label className="waitlist-consent">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          aria-required="true"
          aria-invalid={fieldErrors.consent ? 'true' : undefined}
          aria-describedby={fieldErrors.consent ? 'waitlist-consent-error' : undefined}
        />
        <span>
          Akceptuję{' '}
          <a href="/privacy.html" target="_blank" rel="noopener noreferrer">
            Politykę prywatności
          </a>{' '}
          i wyrażam zgodę na przechowywanie mojego adresu email w celu kontaktu w sprawie waitlist.
        </span>
      </label>
      {fieldErrors.consent && (
        <p id="waitlist-consent-error" className="waitlist-field-error" role="alert">
          {fieldErrors.consent}
        </p>
      )}

      <button type="submit" className="waitlist-submit" disabled={!canSubmit}>
        {state === 'submitting' ? 'Zapisuję...' : 'Zapisz mnie na waitlistę'}
      </button>

      {state === 'error' && serverError && (
        <div className="waitlist-error" role="alert">
          {serverError}
        </div>
      )}
    </form>
  );
}
