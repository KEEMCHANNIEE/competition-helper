import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API = process.env.VITE_API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/auth': { target: API, changeOrigin: true },
      '/chat': { target: API, changeOrigin: true },
      '/me': { target: API, changeOrigin: true },
      '/workspaces': { target: API, changeOrigin: true },
      '/competitions': { target: API, changeOrigin: true },
      '/recommend': { target: API, changeOrigin: true },
      '/health': { target: API, changeOrigin: true },
    },
  },
})
