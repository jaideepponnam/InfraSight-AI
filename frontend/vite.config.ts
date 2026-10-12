import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const proxy = {
    "/api": {
      target: env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
      changeOrigin: true,
    },
  };
  return {
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, proxy },
    test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"] },
  };
});
