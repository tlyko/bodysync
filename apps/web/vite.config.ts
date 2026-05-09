import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    // Top-level `await` w main.tsx (preview mock dynamic import) wymaga
    // target esnext / chrome89+. Modern browsers OK; iOS 15+ supported.
    target: 'esnext',
  },
});
