/**
 * BOB Robot — Service Worker (sw.js)
 * Enables PWA installation, offline fallback, and Web Push notifications.
 * Runs in the background even when the browser tab is closed.
 */

const CACHE   = 'bob-v1';
const OFFLINE = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/js/joystick.js',
  '/static/js/gauges.js',
  '/static/icons/bob-192.png',
];

// ── Install: cache core assets ──────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(OFFLINE))
  );
  self.skipWaiting();
});

// ── Activate: clean old caches ──────────────────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch: serve from cache if offline ─────────────────────────────────────
self.addEventListener('fetch', e => {
  // Only handle GET, skip video/camera streams
  if (e.request.method !== 'GET') return;
  if (e.request.url.includes('/video_feed')) return;
  if (e.request.url.includes('/ws')) return;

  e.respondWith(
    fetch(e.request)
      .then(res => {
        // Cache successful responses
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

// ── Push notifications (Web Push API — no third party) ──────────────────────
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  const title = data.title || 'BOB Alert';
  const opts  = {
    body:    data.body    || 'BOB has a notification for you.',
    icon:    '/static/icons/bob-192.png',
    badge:   '/static/icons/bob-192.png',
    tag:     data.tag     || 'bob-alert',
    vibrate: data.vibrate || [200, 100, 200],
    data:    { url: data.url || '/' },
    actions: data.actions || [
      { action: 'view',   title: '📷 View Camera' },
      { action: 'dismiss',title: 'Dismiss' },
    ],
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

// ── Notification click: open dashboard ──────────────────────────────────────
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data?.url || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(list => {
        for (const client of list) {
          if (client.url.startsWith(self.location.origin)) {
            return client.focus();
          }
        }
        return clients.openWindow(url);
      })
  );
});
