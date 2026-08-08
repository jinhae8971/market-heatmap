/* 앱 셸은 캐시 우선, 시세 데이터는 네트워크 우선.
   히트맵은 오래된 숫자를 보여주는 게 안 보여주는 것보다 나쁘다.
   그래서 heatmap.json은 항상 네트워크를 먼저 치고, 실패했을 때만 캐시로 떨어진다. */
const SHELL = 'heatmap-shell-v3';
const DATA  = 'heatmap-data-v1';
const ASSETS = [
  './', './index.html', './manifest.webmanifest',
  './icons/icon-192.png', './icons/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== SHELL && k !== DATA).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;

  if (url.pathname.endsWith('heatmap.json')) {
    e.respondWith(
      fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(DATA).then(c => c.put('data', copy));
        return res;
      }).catch(() => caches.open(DATA).then(c => c.match('data')))
    );
    return;
  }

  if (url.origin === location.origin) {
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
  }
});
