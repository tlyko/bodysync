/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Preview mock mode flag. Set w Cloudflare Workers Builds dashboard →
   * Settings → Variables → Preview environment. Production environment
   * NIE ma tego ustawienia (mock chunk tree-shaken przez Vite z prod bundle).
   */
  readonly VITE_PREVIEW_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
