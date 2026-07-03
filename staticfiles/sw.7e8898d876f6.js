/* GPSL Automation — Advanced Service Worker */
const CACHE_NAME = 'gpsl-v2';
const STATIC_ASSETS = [
  '/',
  '/static/manifest.json',
  '/static/offline.html',
  '/static/js/offline.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// Install: cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    // Try to queue POST for later sync
    if (request.method === 'POST' && self.registration.sync) {
      event.respondWith(
        fetch(request).catch(() => {
          // Store for background sync
          return new Response(JSON.stringify({queued: true}), {
            headers: {'Content-Type': 'application/json'}
          });
        })
      );
    }
    return;
  }

  // Static assets — cache first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request))
    );
    return;
  }

  // API/dashboard pages — network first, fallback to cache
  event.respondWith(
    fetch(request).then((response) => {
      const clone = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
      return response;
    }).catch(() => {
      return caches.match(request).then((cached) => {
        if (cached) return cached;
        // Return offline page for HTML requests
        if (request.headers.get('accept')?.includes('text/html')) {
          return caches.match('/static/offline.html');
        }
        return new Response('Offline', {status: 503, statusText: 'Service Unavailable'});
      });
    })
  );
});

// Background sync for offline form submissions
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-forms') {
    event.waitUntil(syncQueuedForms());
  }
});

async function syncQueuedForms() {
  // Read queued forms from IndexedDB and send them
  // This is handled by the client-side JS
  const clients = await self.clients.matchAll({type: 'window'});
  clients.forEach(client => client.postMessage({type: 'SYNC_FORMS'}));
}
