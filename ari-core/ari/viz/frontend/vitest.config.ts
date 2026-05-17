import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

/**
 * Vitest configuration for the ARI viz frontend.
 *
 * Enables React Testing Library + jsdom so component tests can render
 * tsx, simulate clicks, and assert against the DOM. Mirrors the
 * (minimal) Vite config used by the dev server, so component imports
 * resolve identically in tests and in the production bundle.
 *
 * Run: `npm test` (single pass) or `npm run test:watch`.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/__tests__/**/*.test.tsx', 'src/**/*.test.tsx'],
    css: false,
  },
});
