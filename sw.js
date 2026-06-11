/**
 * GPSL ERP Service Worker
 * Enables PWA install, offline fallback, and asset caching
 */

const CACHE_NAME = 'gpsl-erp-v1';
const OFFLINE_URL = '/offline/';

// Assets to cache immediately on install
const STATIC_ASSETS = [
  '/',
  '/offline/',
  '/static/css/main.css',
];

// ── INSTALL ──
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(() => {
        // If any static asset fails, continue anyway
        return Promise.resolve();
      });
    }).then(() => self.skipWaiting())
  );
});

// ── ACTIVATE ──
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// ── FETCH ──
self.addEventListener('fetch', event => {
  // Only handle GET requests
  if (event.request.method !== 'GET') return;

  // Skip admin, API and media requests
  const url = new URL(event.request.url);
  if (
    url.pathname.startsWith('/system-admin/') ||
    url.pathname.startsWith('/media/') ||
    url.pathname.startsWith('/api/')
  ) return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful page responses
        if (
          response.ok &&
          response.type === 'basic' &&
          !url.pathname.startsWith('/static/')
        ) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, clone);
          });
        }
        return response;
      })
      .catch(() => {
        // Network failed — try cache
        return caches.match(event.request).then(cached => {
          if (cached) return cached;
          // If no cache, show offline page for navigation requests
          if (event.request.mode === 'navigate') {
            return caches.match(OFFLINE_URL);
          }
          return new Response('Offline', { status: 503 });
        });
      })
  );
});
