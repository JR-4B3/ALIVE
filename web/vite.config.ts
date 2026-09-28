import { rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vite';

// `vite build` writes the clean visitor page to docs/ for GitHub Pages.
// `vite build --mode debug` writes the separate diagnostics page to docs/debug/.
export default defineConfig(({ mode }) => {
  const debug = mode === 'debug';
  const voice = mode === 'voice';
  return {
    base: './',
    root: voice ? fileURLToPath(new URL('./voice', import.meta.url)) : undefined,
    define: { __DEBUG_UI__: JSON.stringify(debug) },
    build: {
      outDir: fileURLToPath(new URL(voice ? '../docs/voice' : debug ? '../docs/debug' : '../docs', import.meta.url)),
      // docs/ holds hand-made files (QR code, wiring diagrams) that must
      // survive the build, so only hashed bundles are cleared beforehand.
      emptyOutDir: debug || voice,
      rollupOptions: debug || voice ? {} : { plugins: [cleanDocsAssets()] }
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
