/* LamTo resident service worker.
 * Caches only versioned static assets and the offline shell.
 * Never caches authenticated HTML, API responses, documents, or mutations.
 */
const VERSION = "lamto-web-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const STATIC_CACHE = `${VERSION}-static`;
const OFFLINE_URL = "/offline/";
const PRECACHE_URLS = [
  OFFLINE_URL,
  "/static/web/app.css",
  "/static/web/manifest.webmanifest",
  "/static/web/icons/icon-192.png",
  "/static/web/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith("lamto-web-") && key !== SHELL_CACHE && key !== STATIC_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  return url.pathname.startsWith("/static/");
}

function isMutation(request) {
  return request.method !== "GET" && request.method !== "HEAD";
}

function isAuthenticatedHtmlPath(url) {
  // Resident app routes and other authenticated pages must always hit the network.
  if (url.pathname === "/" || url.pathname.startsWith("/r/")) {
    return true;
  }
  if (url.pathname.startsWith("/admin/") || url.pathname.startsWith("/accounts/")) {
    return true;
  }
  return false;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    return;
  }

  // Never cache mutations, documents, or APIs.
  if (isMutation(request) || url.pathname.startsWith("/documents/") || url.pathname.startsWith("/api/")) {
    return;
  }

  if (isAuthenticatedHtmlPath(url)) {
    // Network-only for authenticated app HTML.
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL).then((cached) => cached || Response.error()))
    );
    return;
  }

  if (isStaticAsset(url) || url.pathname === OFFLINE_URL || url.pathname.endsWith("manifest.webmanifest")) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) {
          return cached;
        }
        const response = await fetch(request);
        if (response && response.ok) {
          cache.put(request, response.clone());
        }
        return response;
      }).catch(() => caches.match(OFFLINE_URL))
    );
  }
});
