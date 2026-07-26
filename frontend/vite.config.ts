import { defineConfig } from 'vite';
import { resolve } from 'node:path';

// El código fuente vive en frontend/ pero el HTML y los assets siguen en la raíz del repo
// durante la migración incremental. La build emite a ../dist para que el backend la sirva.
export default defineConfig({
  root: resolve(__dirname, '..'),
  publicDir: false,
  build: {
    outDir: resolve(__dirname, '../dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, '../index.html'),
    },
  },
  test: {
    globals: true,
    environment: 'node',
    include: ['frontend/tests/**/*.test.ts'],
  },
});
