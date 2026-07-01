import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In `npm run dev`, proxy /api to the local API. In the container, nginx does this.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
