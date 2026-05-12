import { useEffect, useRef, useState } from 'react';
import { GOOGLE_CLIENT_ID } from '../config';
import { loginWithGoogle } from '../api';
import logoHorizontal from '../assets/logo-horizontal.svg';
import { WaitlistForm } from './WaitlistForm';
import { DemoGallery } from './DemoGallery';

// Google Identity Services types — minimum potrzebne, biblioteka inject'uje
// `window.google.accounts.id` po załadowaniu skryptu z gsi/client.
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
            auto_select?: boolean;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: {
              theme?: 'outline' | 'filled_blue' | 'filled_black';
              size?: 'small' | 'medium' | 'large';
              shape?: 'rectangular' | 'pill';
              text?: 'signin_with' | 'signup_with' | 'continue_with' | 'signin';
              locale?: string;
            },
          ) => void;
          prompt: () => void;
        };
      };
    };
  }
}

type Props = {
  onLoginSuccess: () => void;
};

export function LoginScreen({ onLoginSuccess }: Props) {
  // PR2 waitlist — Google login button schowany za toggle żeby waitlist był
  // primary CTA. Owner + Weronika klikają "Mam już konto → Zaloguj" → reveals.
  const [showLogin, setShowLogin] = useState(false);
  const buttonRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !showLogin) {
      return;
    }
    let attempts = 0;
    const maxAttempts = 50; // 5s total

    const init = () => {
      if (!window.google?.accounts?.id) {
        attempts += 1;
        if (attempts < maxAttempts) {
          setTimeout(init, 100);
        }
        return;
      }

      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (response) => {
          try {
            await loginWithGoogle(response.credential);
            onLoginSuccess();
          } catch (e) {
            // 401/403/500 — pokaż w konsoli, user kliknie ponownie
            console.error('login failed', e);
          }
        },
        auto_select: false,
      });

      if (buttonRef.current) {
        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: 'filled_black',
          size: 'large',
          shape: 'pill',
          text: 'signin_with',
          locale: 'pl',
        });
      }
    };

    init();
  }, [onLoginSuccess, showLogin]);

  return (
    <div className="login-screen">
      <div className="waitlist-hero">
        <img src={logoHorizontal} alt="bodysync" className="login-logo" />
        <h1>Osobisty asystent AI dla treningu i diety</h1>
        <p className="waitlist-pitch">
          <strong>bodysync</strong> łączy dane z Apple Health, Strava i Twojego planu treningowego,
          żeby dawać Ci codzienne rekomendacje po polsku — co zjeść, jak się zregenerować, kiedy
          odpuścić. Aplikacja w fazie zamkniętej bety, dla par i osób uzależnionych od danych.
          Zostaw email — odezwę się gdy ruszymy szerzej.
        </p>
      </div>

      <DemoGallery />

      <div className="waitlist-hero">
        <WaitlistForm />

        <button
          type="button"
          className="login-toggle"
          onClick={() => setShowLogin((s) => !s)}
          aria-expanded={showLogin}
          aria-controls="login-reveal"
        >
          Mam już konto → Zaloguj
        </button>

        {showLogin && (
          <div id="login-reveal" className="login-reveal">
            {GOOGLE_CLIENT_ID ? (
              <div ref={buttonRef} className="gsi-button" />
            ) : (
              <p className="error">
                Konfiguracja niekompletna — brak <code>VITE_GOOGLE_CLIENT_ID</code>.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
