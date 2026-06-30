import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev: `npm run dev` proxies the API to the FastAPI co-pilot service so SSE / artifacts
// work same-origin. Override the target with VITE_API_TARGET (default = the 5090 box).
// Prod: `npm run build` → dist/, served by FastAPI StaticFiles (same origin, no proxy).
const API = process.env.VITE_API_TARGET || 'http://100.71.161.102:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/session': { target: API, changeOrigin: true },
      '/demo': { target: API, changeOrigin: true },
    },
  },
})
