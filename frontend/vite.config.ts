import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // 控制台挂在 FastAPI 的 /console/ 子路径下，资源必须用相对路径引用
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    proxy: {
      // Dev 时代理到本地 FastAPI：pnpm dev 搭配 scripts/serve_console.py 使用
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    // 构建产物直接输出到 FastAPI 挂载的 console 目录（部署方式与旧版一致）
    outDir: '../src/agent_core/api/console',
    emptyOutDir: true,
  },
})
