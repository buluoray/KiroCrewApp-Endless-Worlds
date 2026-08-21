import { defineConfig } from 'vite'

import manifest from '../app.json'

// Single source of truth: the version shown in the app footer is read from the
// manifest at build time, so a bump in app.json cannot drift from the UI.
const APP_VERSION: string = manifest.version

/**
 * Builds the app's UI into a single ES module the dashboard loads directly.
 *
 * The load-bearing decision here is `external`. The dashboard serves this file
 * to a browser whose import map already provides React and the host component
 * library, and it hands the SAME React instance to every app. Bundling React
 * would produce a SECOND copy: hooks then throw "invalid hook call" from inside
 * a component that looks perfectly ordinary, which is among the least
 * diagnosable failures in the ecosystem. So every specifier the host map owns
 * stays an import in the output, exactly as the hand-written module had it.
 *
 * `react` and `react-dom` are still devDependencies — TypeScript needs the types
 * to check against, and Vite needs to resolve them during dev. They are simply
 * never emitted.
 */
const HOST_PROVIDED = [
  'react',
  'react-dom',
  'react/jsx-runtime',
  'react-dom/client',
  'lucide-react',
  '@tanstack/react-query',
  '@kirocrew/app-sdk',
  '@kirocrew/ui',
]

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  build: {
    // Straight into the directory the manifest's `ui.entry` names, so a build is
    // the only step between source and what the dashboard serves.
    outDir: '../ui',
    emptyOutDir: false, // icon.svg lives there and is not ours to delete
    // A library build: no HTML entry, no hashed asset names, one predictable file.
    lib: {
      entry: 'src/main.tsx',
      formats: ['es'],
      fileName: () => 'index.mjs',
    },
    rollupOptions: {
      external: HOST_PROVIDED,
    },
    // The dashboard is a modern-browser surface; a legacy transpile would only
    // make the output bigger and harder to read.
    target: 'es2022',
    minify: false, // this is read by humans debugging a live app more than by machines
    sourcemap: false,
  },
})
