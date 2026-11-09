import { build, context } from 'esbuild';
import { mkdirSync, copyFileSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, 'dist');
mkdirSync(dist, { recursive: true });

const watch = process.argv.includes('--watch');

/** Inline every asset into a single self-contained page: no file:// fetches, no CORS. */
function inlineIndex() {
  copyFileSync(join(root, 'src/editor.css'), join(dist, 'editor.css'));
  const html = readFileSync(join(root, 'src/index.html'), 'utf8');
  const css = readFileSync(join(dist, 'editor.css'), 'utf8');
  const js = readFileSync(join(dist, 'editor.js'), 'utf8');
  writeFileSync(
    join(dist, 'index.html'),
    html
      .replace('/*__CSS__*/', () => css)
      .replace('/*__JS__*/', () => js),
  );
}

const options = {
  entryPoints: {
    editor: join(root, 'src/editor.mjs'),
  },
  bundle: true,
  format: 'iife',
  target: ['chrome80'],
  minify: !watch,
  sourcemap: false,
  outdir: dist,
  loader: { '.ttf': 'dataurl', '.woff2': 'dataurl' },
  legalComments: 'none',
  logLevel: 'info',
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  inlineIndex();
  console.log('watching…');
} else {
  await build(options);
  inlineIndex();
  copyFileSync(join(root, 'src/README-ASSETS.txt'), join(dist, 'README-ASSETS.txt'));
  console.log('built dist/index.html');
}
