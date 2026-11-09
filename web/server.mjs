#!/usr/bin/env node
/**
 * Static file server for the editor preview (no dependencies).
 * Used by `npm run preview` and by the Arena live preview.
 */
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(fileURLToPath(import.meta.url), '..', 'dist');
const port = Number(process.env.PORT || 8080);
const host = process.env.HOST || '0.0.0.0';

const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
};

const server = createServer(async (req, res) => {
  let path = decodeURIComponent((req.url || '/').split('?')[0]);
  if (path === '/' || path === '') path = '/preview.html';
  const file = join(root, normalize(path).replace(/^(\.\.[/\\])+/, ''));
  try {
    const info = await stat(file);
    if (!info.isFile()) throw new Error('not a file');
    const body = await readFile(file);
    res.writeHead(200, {
      'Content-Type': types[extname(file)] || 'application/octet-stream',
      'Cache-Control': 'no-store',
      // The preview is proxied through the Arena host, so no framing restrictions.
      'X-Frame-Options': 'ALLOWALL',
      'Content-Security-Policy': '',
    });
    res.end(body);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('not found: ' + path);
  }
});

server.listen(port, host, () => {
  console.log(`REA editor preview on http://${host}:${port}/ (root: ${root})`);
});
