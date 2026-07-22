import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Локальная разработка: фронт на :5173, бэкенд FastAPI на :8080.
// Дев-сервер проксирует /api на бэкенд.
const API_TARGET = process.env.VITE_API_TARGET || "http://localhost:8080";

// В проде приложение живёт под /bloggers/ (главный nginx на VPS), поэтому
// сборка идёт с этим base. В деве base=/ — удобнее локально.
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/bloggers/" : "/",
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
}));
