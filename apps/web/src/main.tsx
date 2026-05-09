import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './index.css';

// Preview mock mode dla Cloudflare Workers Builds branch deployments.
// Owner ustawia VITE_PREVIEW_MODE=true w CF dashboard → Settings → Variables
// → Preview environment. Production environment NIE ma flagi → mock NIE
// shipped (dynamic import = osobny chunk, tree-shaken przy build prod).
if (import.meta.env.VITE_PREVIEW_MODE === 'true') {
  const { installPreviewMock } = await import('./preview-mock');
  installPreviewMock();
}

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('#root not found');

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
