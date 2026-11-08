import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const SIDECAR = 'http://127.0.0.1:8756'

export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: SIDECAR, changeOrigin: true },
      '/ws': { target: `ws://127.0.0.1:8756`, ws: true },
    },
  },
})
