import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true, // 5173 이 점유돼 있으면 5174 로 옮겨가지 말고 에러를 낸다(항상 5173 사용)
    proxy: {
      '/auth': { target: API, changeOrigin: true },
      '/chat': { target: API, changeOrigin: true },
      '/notifications': { target: API, changeOrigin: true },
      '/me': { target: API, changeOrigin: true },
      '/workspaces': { target: API, changeOrigin: true },
      '/competitions': { target: API, changeOrigin: true },
      '/recommend': { target: API, changeOrigin: true },
      '/health': { target: API, changeOrigin: true },
    },
  },
})
