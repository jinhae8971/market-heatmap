/* 캐시 전략
 *   HTML·데이터: 네트워크 우선 (실패 시 캐시)
 *   그 외 정적 자산: 캐시 우선
 *
 * HTML을 캐시 우선으로 두면 배포해도 화면이 바뀌지 않는다.
 * 캐시 버전을 올려도 마찬가지인데, install 단계의 addAll이 브라우저 HTTP 캐시에서
 * 옛 응답을 그대로 받아 새 캐시에 넣기 때문이다. 그래서
 *   (1) install에서 cache:'reload'로 HTTP 캐시를 우회하고
 *   (2) HTML은 아예 네트워크 우선으로 돌린다.
 */
const SHELL = 'heatmap-shell-v10';
const RUNTIME = 'heatmap-runtime-v10';
const ASSETS = [
  './', './index.html', './semi.html', './trend.html', './manifest.webmanifest',
  './icons/icon-192.png', './icons/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const c = await caches.open(SHELL);
    // cache:'reload' — 브라우저 HTTP 캐시를 건너뛰고 원본에서 받는다
    await Promise.all(ASSETS.map(u =>
      fetch(new Request(u, { cache: 'reload' }))
        .then(r => r.ok && c.put(u, r))
        .catch(() => {})
    ));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter(k => k !== SHELL && k !== RUNTIME)
      .map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

function isFresh(url) {
  return url.pathname.endsWith('.json')
      || url.pathname.endsWith('.html')
      || url.pathname.endsWith('/');
}

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  if (isFresh(url)) {
    // 네트워크 우선 — 배포한 것이 다음 실행에 반드시 보인다
    e.respondWith((async () => {
      try {
        const res = await fetch(e.request);
        const c = await caches.open(RUNTIME);
        c.put(e.request, res.clone());
        return res;
      } catch (err) {
        const hit = await caches.match(e.request);
        return hit || Response.error();
      }
    })());
    return;
  }

  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});
