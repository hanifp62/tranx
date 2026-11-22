import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

const CONFIG_DIR = dirname(fileURLToPath(import.meta.url));

function strictPreviewMalformedSlashPlugin(): Plugin {
  return {
    name: 'tranx-strict-preview-malformed-slash',
    configurePreviewServer(server) {
      const distDir = resolve(CONFIG_DIR, 'dist');
      const indexHtmlPath = resolve(distDir, 'index.html');
      server.middlewares.use((req, res, next) => {
        const rawUrl = req.url || '';
        const qIdx = rawUrl.indexOf('?');
        const rawPath = qIdx >= 0 ? rawUrl.slice(0, qIdx) : rawUrl;
        // Skip existing static files inside dist/ (assets, manifest, sw, icons, 404.html)
        if (rawPath !== '/' && !rawPath.includes('..') && !rawPath.includes('//')) {
          const candidate = resolve(distDir, rawPath.replace(/^\/+/, ''));
          if (candidate.startsWith(distDir) && existsSync(candidate)) {
            next();
            return;
          }
        }
        // Prevent Connect/sirv from silently redirecting "///" -> "/" or serving plain text on dot-paths
        // during local preview/E2E so tranX's strict routeGuard renders 404 directly.
        if (
          rawPath.includes('//') ||
          rawPath.includes('.') ||
          /%(?:2e|2f|5c)/i.test(rawPath)
        ) {
          if (existsSync(indexHtmlPath)) {
            const html = readFileSync(indexHtmlPath, 'utf-8');
            res.statusCode = 200;
            res.setHeader('Content-Type', 'text/html; charset=utf-8');
            res.end(html);
            return;
          }
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [
    strictPreviewMalformedSlashPlugin(),
    react(),
    VitePWA({
      registerType: 'prompt',
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
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        globPatterns: ['**/*.{js,css,html,svg,png}'],
        globIgnores: [
          '**/pdf-*.js',
          '**/pdf.worker*',
          '**/worker.min*',
          '**/directEngine-*',
          '**/SubViews-*',
          '**/MangaLinkReader-*',
          '**/screenshots/**',
          '**/404.html',
        ],
        navigateFallback: '/index.html',
        navigateFallbackAllowlist: [
          /^\/$/,
          /^\/masuk(?:\/kode)?$/,
          /^\/berkas$/,
          /^\/kamus(?:\/[A-Za-z0-9_-]{1,128})?$/,
          /^\/c\/[A-Za-z0-9_-]{1,128}(?:\/m\/[A-Za-z0-9_-]{1,128}\/baca)?$/,
          /^\/web$/,
          /^\/share$/,
          /^\/open$/,
          /^\/r\/.+$/,
        ],
        navigateFallbackDenylist: [/^\/v1\//, /^\/__\//, /^\/404\.html$/, /^\/\.well-known\//, /^\/(?!r\/).*\/{2,}/],
        runtimeCaching: [
          {
            urlPattern: ({ sameOrigin, url }) =>
              sameOrigin && /^\/assets\/.+\.(?:js|css)$/i.test(url.pathname),
            handler: 'CacheFirst',
            options: {
              cacheName: 'tranx-app-chunks-v2',
              expiration: {
                maxEntries: 64,
                maxAgeSeconds: 30 * 24 * 60 * 60,
              },
            },
          },
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
          {
            urlPattern: ({ url }) => url.origin === 'https://fonts.gstatic.com',
            handler: 'CacheFirst',
            options: {
              cacheName: 'tranx-ebook-fonts-v1',
              cacheableResponse: { statuses: [200] },
              expiration: {
                maxEntries: 180,
                maxAgeSeconds: 365 * 24 * 60 * 60,
              },
            },
          },
          {
            urlPattern: ({ url }) => url.origin === 'https://fonts.googleapis.com',
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'tranx-ebook-font-css-v1',
              cacheableResponse: { statuses: [200] },
              expiration: {
                maxEntries: 24,
                maxAgeSeconds: 30 * 24 * 60 * 60,
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
    modulePreload: {
      resolveDependencies: (_filename, deps) =>
        deps.filter(
          (d) => !/(?:firebase-db|firebase-storage|pdf\.worker|tesseract|directEngine)/i.test(d)
        ),
    },
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-dom/client', 'react/jsx-runtime'],
          'firebase-auth': ['firebase/app', 'firebase/auth'],
          'firebase-db': ['firebase/firestore'],
        },
      },
    },
  },
});
