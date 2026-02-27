import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://app:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      '/ws': {
        target: backend,
        ws: true,
      },
    },
    watch: {
      usePolling: true,
    },
  },
})
