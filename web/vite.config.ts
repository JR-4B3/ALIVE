import { rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vite';

// Public API for the published pages, so the bare GitHub Pages link works.
const PUBLISHED_API = 'https://t480.tail688a7b.ts.net';

// `vite build` writes the clean visitor page to docs/ for GitHub Pages.
// `vite build --mode debug` writes the separate diagnostics page to docs/debug/.
export default defineConfig(({ mode }) => {
  const debug = mode === 'debug';
  return {
    base: './',
    define: {
      __DEBUG_UI__: JSON.stringify(debug),
      // `vite dev` keeps same-origin requests for local API servers.
      __PUBLISHED_API__: JSON.stringify(mode === 'development' ? '' : PUBLISHED_API)
    },
    build: {
      outDir: debug ? '../docs/debug' : '../docs',
      // docs/ holds hand-made files (QR code, wiring diagrams) that must
      // survive the build, so only hashed bundles are cleared beforehand.
      emptyOutDir: debug,
      rollupOptions: debug ? {} : { plugins: [cleanDocsAssets()] }
    }
  };
});

function cleanDocsAssets(): Plugin {
  return {
    name: 'clean-docs-assets',
    buildStart() {
      rmSync(fileURLToPath(new URL('../docs/assets', import.meta.url)), {
        recursive: true,
        force: true
      });
    }
  };
}
