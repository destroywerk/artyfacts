import { defineConfig } from "astro/config";

export default defineConfig({
  output: "static",
  prefetch: true,
  vite: {
    build: {
      cssMinify: "lightningcss",
    },
  },
});
