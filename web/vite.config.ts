import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: [
        'favicon.svg',
        'icons/icon-192.png',
        'icons/icon-512.png',
        'icons/apple-touch-icon.png',
      ],
      manifest: {
        name: 'tranX',
        short_name: 'tranX',
        description:
          'Penerjemah teks, gambar, dokumen, dan tautan Jepang ke bahasa Indonesia atau Inggris dengan konsistensi nama tokoh.',
        theme_color: '#17695B',
        background_color: '#FAFBFA',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        scope: '/',
        lang: 'id',
        icons: [
          {
            src: '/icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any maskable',
          },
          {
            src: '/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable',
          },
        ],
        share_target: {
          action: '/share',
          method: 'GET',
          params: {
            title: 'title',
            text: 'text',
            url: 'url',
          },
        },
        file_handlers: [
          {
            action: '/open',
            accept: {
              'application/epub+zip': ['.epub'],
              'application/pdf': ['.pdf'],
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
              'text/plain': ['.txt', '.srt', '.vtt', '.ass', '.md'],
              'text/html': ['.html', '.htm'],
            },
          },
        ],
      },
      workbox: {
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        globPatterns: ['**/*.{js,css,html,svg,png}'],
        globIgnores: ['**/pdf.worker*', '**/worker.min*'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/v1\//],
      },
    }),
  ],
  build: {
    target: 'esnext',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-dom/client', 'react/jsx-runtime'],
          'firebase-auth': ['firebase/app', 'firebase/auth', 'firebase/storage'],
          'firebase-db': ['firebase/firestore'],
        },
      },
    },
  },
});
