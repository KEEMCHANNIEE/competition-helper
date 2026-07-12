import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 컨테이너 안에서 vite dev 서버를 돌릴 때(docker-compose.dev.yml)는 "localhost"가
// 컨테이너 자기 자신을 가리켜 api 서비스에 못 닿는다. VITE_API_URL이 있으면 그걸 쓰고,
// 없으면(호스트에서 직접 npm run dev) 기존처럼 localhost:8000으로 프록시한다.
const API = process.env.VITE_API_URL || 'http://localhost:8000'

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
