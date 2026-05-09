import { useEffect, useRef } from 'react';
import { GOOGLE_CLIENT_ID } from '../config';
import { loginWithGoogle } from '../api';
import logoHorizontal from '../assets/logo-horizontal.svg';

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
  const buttonRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) {
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
  }, [onLoginSuccess]);

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div className="login-screen">
        <img src={logoHorizontal} alt="bodysync" className="login-logo" />
        <p className="error">
          Konfiguracja niekompletna — brak <code>VITE_GOOGLE_CLIENT_ID</code>. Ustaw w
          Cloudflare project Environment Variables i przebuduj.
        </p>
      </div>
    );
  }

  return (
    <div className="login-screen">
      <img src={logoHorizontal} alt="bodysync" className="login-logo" />
      <p className="tagline">Personal health + fitness dashboard</p>
      <div ref={buttonRef} className="gsi-button" />
    </div>
  );
}
