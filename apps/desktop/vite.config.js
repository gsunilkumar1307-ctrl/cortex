import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) {
            if (id.includes("react-syntax-highlighter")) {
              return "syntax-highlighter";
            }
            if (id.includes("@assistant-ui") || id.includes("@radix-ui")) {
              return "assistant-ui";
            }
            return "vendor";
          }
        },
      },
    },
  },
});
