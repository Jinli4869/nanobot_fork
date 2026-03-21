import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendTarget = "http://127.0.0.1:18791";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: {
      "/health": backendTarget,
      "/sessions": backendTarget,
      "/chat": backendTarget,
      "/runtime": backendTarget,
      "/tasks": backendTarget,
    },
  },
  test: {
    environment: "jsdom",
  },
});
