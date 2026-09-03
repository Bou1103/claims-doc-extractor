import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, proxy the API routes to uvicorn on :8000 so the app calls same-origin
// paths. `npm run build` emits static assets that FastAPI serves itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/v1': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
