import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  if (command === "build") {
    const origin = new URL(env.VITE_API_BASE_URL || "");
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname);
    if (
      (origin.protocol !== "https:" &&
        !(local && origin.protocol === "http:")) ||
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash ||
      !env.VITE_API_READ_KEY?.trim()
    )
      throw new Error(
        "Production builds require an API origin and public demo read key.",
      );
  }
  const proxy = {
    "/api": {
      target: env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
      changeOrigin: true,
    },
  };
  return {
    plugins: [react()],
    // Carbon still uses legacy Sass if(); silence only that known deprecation.
    // Keep other compiler warnings and errors visible.
    css: {
      preprocessorOptions: {
        scss: { quietDeps: true, silenceDeprecations: ["if-function"] },
      },
    },
    // Only these two public values enter client code, never other VITE_* variables.
    envPrefix: [],
    define: {
      "import.meta.env.VITE_API_BASE_URL": JSON.stringify(
        env.VITE_API_BASE_URL || "",
      ),
      "import.meta.env.VITE_API_READ_KEY": JSON.stringify(
        env.VITE_API_READ_KEY || "",
      ),
    },
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, proxy },
    test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"] },
  };
});
