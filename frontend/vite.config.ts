import tailwindcss from '@tailwindcss/postcss';
import react from '@vitejs/plugin-react';
import { defineConfig, type ProxyOptions } from 'vite';
import { fileURLToPath, URL } from 'node:url';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

function consultationToken(): string {
  if (process.env.PDOH_API_TOKEN) return process.env.PDOH_API_TOKEN;
  try {
    const envText = readFileSync(resolve(import.meta.dirname, '../api/.env.api'), 'utf8');
    const line = envText.split(/\r?\n/).find((entry) => entry.startsWith('PDOH_API_TOKEN='));
    return line?.slice('PDOH_API_TOKEN='.length).trim() ?? '';
  } catch { return ''; }
}

const consultationProxy: ProxyOptions = {
  target: process.env.PDOH_CONSULTA_URL || 'http://127.0.0.1:8000',
  changeOrigin: true,
  configure(proxy) {
    proxy.on('proxyReq', (proxyReq) => {
      const token = consultationToken();
      if (token) proxyReq.setHeader('Authorization', `Bearer ${token}`);
    });
  },
};

export default defineConfig({
  css: { postcss: { plugins: [tailwindcss()] } },
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('.', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 5173, proxy: { '/api/v1': consultationProxy, '/api/v2': consultationProxy } },
  preview: { host: '127.0.0.1', port: 4173, proxy: { '/api/v1': consultationProxy, '/api/v2': consultationProxy } },
});
