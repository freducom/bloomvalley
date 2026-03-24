const CACHE_NAME = "bloomvalley-v1";

// Pages to precache (app shell)
const PRECACHE_URLS = [
  "/portfolio",
  "/recommendations",
  "/holdings",
];

// API paths to cache with network-first strategy
const CACHEABLE_API = [
  "/api/v1/portfolio/summary",
  "/api/v1/portfolio/holdings",
  "/api/v1/recommendations",
  "/api/v1/dividends/income-projection",
  "/api/v1/quotes/live",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

function isNavigationToOfflinePage(request) {
  if (request.mode !== "navigate") return false;
  const url = new URL(request.url);
  return ["/portfolio", "/recommendations", "/holdings"].some(
    (p) => url.pathname === p || url.pathname.startsWith(p + "/")
  );
}

function isCacheableApi(request) {
  const url = new URL(request.url);
  return CACHEABLE_API.some((p) => url.pathname.startsWith(p));
}

// Network-first: try network, fall back to cache
async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw new Error("No cached response available");
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Skip non-GET
  if (request.method !== "GET") return;

  // Navigation to offline-capable pages
  if (isNavigationToOfflinePage(request)) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Cacheable API calls
  if (isCacheableApi(request)) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Static assets (JS/CSS) — cache-first
  const url = new URL(request.url);
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      })
    );
    return;
  }
});
