import { useState } from 'react';

// Demo gallery na landing page — pokazuje screeny z working dashboardu jako
// zajawkę dla osób które zapisują się na waitlist. Screeny w `public/demo/`
// (`dashboard.png`, `chat.png`, `plan.png`, `cialo.png`) — captured via
// Playwright z preview-mock data, deterministyczne, bez personal danych.
//
// Click na thumbnail → modal z pełnym screenem (lightbox). ESC + click overlay
// closes. KISS: brak carousel/swipe — proste grid 2-col desktop, stack mobile.

type DemoSlide = {
  src: string;
  alt: string;
  caption: string;
};

const SLIDES: DemoSlide[] = [
  {
    src: '/demo/dashboard.png',
    alt: 'Dashboard bodysync z wykresami HRV, snu, kalorii i Recovery',
    caption: 'Dashboard — HRV, sen, kalorie, kroki i Recovery w jednym widoku',
  },
  {
    src: '/demo/chat.png',
    alt: 'Chat AI po polsku z propozycją śniadania przed treningiem',
    caption: 'Asystent AI po polsku — kontekst z Twoich danych + 139 polskich przepisów',
  },
  {
    src: '/demo/plan.png',
    alt: 'Plan treningowy z rozgrzewką i ćwiczeniami',
    caption: 'Plan treningowy — synchronizacja z Google Sheets, automatyczny parsing',
  },
  {
    src: '/demo/cialo.png',
    alt: 'Sekcja Ciało z biometrią z Apple Health',
    caption: 'Biometria — Apple Health → trendy 30 dni (HRV, sen, RHR, body fat)',
  },
];

export function DemoGallery() {
  const [active, setActive] = useState<DemoSlide | null>(null);

  return (
    <section className="demo-gallery" aria-label="Zajawka działającej aplikacji">
      <h2 className="demo-gallery-heading">Zobacz, co dostaniesz</h2>
      <div className="demo-gallery-grid">
        {SLIDES.map((s) => (
          <button
            key={s.src}
            type="button"
            className="demo-gallery-tile"
            onClick={() => setActive(s)}
            aria-label={`Powiększ: ${s.caption}`}
          >
            <img src={s.src} alt={s.alt} loading="lazy" />
            <span className="demo-gallery-caption">{s.caption}</span>
          </button>
        ))}
      </div>

      {active && (
        <div
          className="demo-gallery-modal"
          role="dialog"
          aria-modal="true"
          aria-label={active.caption}
          onClick={() => setActive(null)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setActive(null);
          }}
        >
          <button
            type="button"
            className="demo-gallery-modal-close"
            onClick={() => setActive(null)}
            aria-label="Zamknij"
          >
            ✕
          </button>
          <img src={active.src} alt={active.alt} />
          <p className="demo-gallery-modal-caption">{active.caption}</p>
        </div>
      )}
    </section>
  );
}
