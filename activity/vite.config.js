import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

const activityRoot = fileURLToPath(new URL('.', import.meta.url));

// L'app Activity est buildée (`npm run build`) puis servie par Flask, sur la MÊME
// origine que /api/token (architecture mono-serveur). Le bloc `server` ne sert que
// pour `npm run dev` (HMR), prévu plus tard.
export default defineConfig({
  envDir: '..',          // lit le .env À LA RACINE du projet (VITE_DISCORD_CLIENT_ID)
  base: './',            // chemins d'assets relatifs → servis par Flask sous /assets
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: `${activityRoot}index.html`,
        bridge: `${activityRoot}src/bridge.js`,
      },
      output: {
        entryFileNames: (chunk) => (
          chunk.name === 'bridge'
            ? 'assets/activity-bridge.js'
            : 'assets/[name]-[hash].js'
        ),
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    proxy: {
      // Adapter le port si WEBAPP_PORT diffère (Flask).
      '/api': { target: 'http://localhost:8001', changeOrigin: true },
      '/.proxy/api': { target: 'http://localhost:8001', changeOrigin: true },
    },
    hmr: { clientPort: 443 },
  },
});
