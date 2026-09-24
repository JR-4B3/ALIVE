import { rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vite';

// `vite build` writes the clean visitor page to docs/ for GitHub Pages.
// `vite build --mode debug` keeps the diagnostics UI in web/dist-debug/.
export default defineConfig(({ mode }) => {
  const debug = mode === 'debug';
  return {
    base: './',
    define: { __DEBUG_UI__: JSON.stringify(debug) },
    build: {
      outDir: debug ? 'dist-debug' : '../docs',
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
