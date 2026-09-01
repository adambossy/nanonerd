import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      // Keep the hand-written public/manifest.webmanifest.
      manifest: false,
      includeAssets: ["icon.svg", "manifest.webmanifest"],
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        // API data is owned by src/offline (IndexedDB), never by the SW cache.
        // Article imagery is the one exception: it is content-addressed and
        // immutable, and an article whose pictures vanish every time the
        // connection drops is not really available offline. CacheFirst means a
        // stored image is never re-requested, so a flapping network cannot
        // take one back off the page. src/offline fills this cache ahead of
        // time by loading each image once (see imageWarmer.ts).
        runtimeCaching: [
          {
            urlPattern: ({ request, url }) =>
              !url.pathname.startsWith("/api/") &&
              (request.destination === "image" ||
                /\.(?:avif|gif|jpe?g|png|svg|webp)$/i.test(url.pathname)),
            handler: "CacheFirst",
            options: {
              cacheName: "article-images",
              // The media host answers cross-origin without CORS headers, so
              // its responses are opaque and report status 0.
              cacheableResponse: { statuses: [0, 200] },
              expiration: {
                maxEntries: 400,
                maxAgeSeconds: 60 * 60 * 24 * 180,
                // Opaque responses are padded heavily against the storage
                // quota; drop the oldest rather than failing to cache at all.
                purgeOnQuotaError: true,
              },
            },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
