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
        runtimeCaching: [],
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
