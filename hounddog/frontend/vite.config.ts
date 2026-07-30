import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: false,
    reportCompressedSize: false,
    rollupOptions: {
      // Cap parallelism so Coolify/small VPS builds don't OOM during transform
      maxParallelFileOps: 2,
      output: {
        manualChunks: {
          antd: ["antd", "@ant-design/icons", "dayjs"],
          react: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
      "/uploads": apiTarget,
      "/ws": {
        target: apiTarget.replace("http", "ws"),
        ws: true,
      },
    },
  },
});
