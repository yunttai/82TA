import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";



export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const privacyDocumentVersion = env.VITE_PRIVACY_DOCUMENT_VERSION;
  if (mode === "production" && (privacyDocumentVersion === undefined || privacyDocumentVersion.length < 1
    || privacyDocumentVersion.length > 64 || privacyDocumentVersion !== privacyDocumentVersion.trim())) {
    throw new Error("Production build requires server-aligned VITE_PRIVACY_DOCUMENT_VERSION (OpenAPI length 1-64, no surrounding whitespace).");
  }

  return {
    plugins: [react()],
    resolve: {
      preserveSymlinks: true,
    },
    server: {
      host: "0.0.0.0",
      allowedHosts: [
        "manatee-purposely-jingle.ngrok-free.dev",
      ],
      proxy: {
        "/api": env.VITE_SERVICE_API_PROXY || "http://127.0.0.1:8000",
      },
    },
    test: {
      environment: "jsdom",
      include: ["src/**/*.test.{ts,tsx}"],
      setupFiles: "./src/test/setup.ts",
    },
  };
});


