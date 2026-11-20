import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        id: '/',
        name: 'tranX',
        short_name: 'tranX',
        description:
          'Penerjemah teks, gambar, dokumen, dan tautan Ebook lintas bahasa Indonesia, Inggris, dan Jepang dengan konsistensi nama tokoh.',
        theme_color: '#17695B',
        background_color: '#FAFBFA',
        display: 'standalone',
        display_override: ['window-controls-overlay', 'standalone'],
        orientation: 'any',
        start_url: '/',
        scope: '/',
        lang: 'id',
        categories: ['books', 'productivity', 'utilities'],
        prefer_related_applications: false,
        related_applications: [
          {
            platform: 'webapp',
            url: 'https://tranx-hanif-id.web.app/manifest.webmanifest',
          },
          {
            platform: 'webapp',
            url: 'https://tranx-hanif-id.firebaseapp.com/manifest.webmanifest',
          },
        ],
        icons: [
          {
            src: '/icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any',
          },
          {
            src: '/icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'maskable',
          },
          {
            src: '/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any',
          },
          {
            src: '/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
        screenshots: [
          {
            src: '/screenshots/desktop-wide.png',
            sizes: '1280x800',
            type: 'image/png',
            form_factor: 'wide',
            label: 'Ruang baca tranX di desktop',
          },
          {
            src: '/screenshots/mobile-narrow.png',
            sizes: '390x844',
            type: 'image/png',
            form_factor: 'narrow',
            label: 'Ruang baca tranX di perangkat seluler',
          },
        ],
        shortcuts: [
          {
            name: 'Terjemahkan Teks',
            short_name: 'Teks',
            url: '/?tab=teks',
            icons: [{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' }],
          },
          {
            name: 'Baca Link & Ebook',
            short_name: 'Link',
            url: '/?tab=link',
            icons: [{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' }],
          },
          {
            name: 'Terjemahkan Dokumen',
            short_name: 'Dokumen',
            url: '/?tab=dokumen',
            icons: [{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' }],
          },
        ],
        share_target: {
          action: '/share',
          method: 'GET',
          enctype: 'application/x-www-form-urlencoded',
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
        navigateFallbackDenylist: [/^\/v1\//, /^\/__\//],
        runtimeCaching: [
          {
            urlPattern: ({ sameOrigin, url }) =>
              sameOrigin && /\.(?:png|jpg|jpeg|webp|svg|woff2?)$/i.test(url.pathname),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'tranx-media-assets-v1',
              expiration: {
                maxEntries: 64,
                maxAgeSeconds: 14 * 24 * 60 * 60,
              },
            },
          },
        ],
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
