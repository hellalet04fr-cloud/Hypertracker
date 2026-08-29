/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Budget JS initial : < 180 ko gzip (§7). Le decoupage par route et l'import
// dynamique de `charts/` sont ce qui le tient — un bundle unique le creverait
// des le premier moteur de trace.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    target: 'es2022',
    cssCodeSplit: true,
    reportCompressedSize: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('react-router')) return 'routeur'
            // `scheduler` appartient au runtime React : le laisser dans `vendor`
            // creait un cycle vendor -> react -> vendor, que Rollup signale et
            // qui empeche le decoupage de tenir sa promesse.
            if (id.includes('react-dom') || id.includes('/react/') || id.includes('scheduler'))
              return 'react'
            return 'vendor'
          }
          return undefined
        },
      },
    },
  },
  worker: { format: 'es' },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: true,
  },
})
