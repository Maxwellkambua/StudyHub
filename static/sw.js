/* StudyHub service worker — offline-first + low-data friendly */
const CACHE = "studyhub-v4";
const SHELL = ["/", "/index.html", "/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (url.origin !== self.location.origin) return;

  // Never cache live endpoints
  if (url.pathname.startsWith("/api/auth") ||
      url.pathname.startsWith("/api/materials/upload") ||
      url.pathname.startsWith("/api/notifications") ||
      url.pathname.startsWith("/api/me/") ||
      url.pathname.startsWith("/api/groups") ||
      url.pathname.startsWith("/api/admin") ||
      url.pathname.startsWith("/ws")) {
    return;
  }

  // Network-first for read-heavy API routes
  if (url.pathname.startsWith("/api/recommendations") ||
      url.pathname.startsWith("/api/materials/search") ||
      url.pathname.startsWith("/api/materials/") ||
      url.pathname.startsWith("/api/bookmarks") ||
      url.pathname.startsWith("/api/courses") ||
      url.pathname.startsWith("/api/universities") ||
      url.pathname.startsWith("/api/leaderboard")) {
    event.respondWith(
      fetch(req)
        .then(res => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then(c => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Cache-first for static assets and the shell
  if (req.method === "GET") {
    event.respondWith(
      caches.match(req).then(hit => hit || fetch(req).then(res => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }))
    );
  }
});
