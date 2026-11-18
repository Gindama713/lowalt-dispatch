import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const proxy = {
  "/api/auth": "http://127.0.0.1:8012",
  "/api/workspace": "http://127.0.0.1:8012",
  "/api/planning": "http://127.0.0.1:8012",
  "/api/assistant": "http://127.0.0.1:8012",
  "/api/telemetry": "http://127.0.0.1:8012",
  "/api/dispatch": "http://127.0.0.1:8012",
};

export default defineConfig({
  plugins: [react()],
  resolve: { dedupe: ["three"] },
  server: { proxy },
  preview: { proxy },
  build: {
    rollupOptions: {
      output: {
        manualChunks: { three: ["three"], react: ["react", "react-dom"] },
      },
    },
  },
});
