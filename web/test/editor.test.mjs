#!/usr/bin/env node
/**
 * Headless smoke test for the editor surface.
 *
 * Runs dist/index.html in jsdom (no browser needed) and drives the same window.ReaIde API that
 * MainActivity calls over the JavaScript bridge. Catches the class of bugs that would otherwise
 * only show up on a device: state bookkeeping between tabs, save throttling, undo history.
 */
import { JSDOM } from 'jsdom';
import { readFileSync } from 'node:fs';


const dist = new URL('../dist/index.html', import.meta.url);
const html = readFileSync(dist, 'utf8');
// Mirrors the WebView environment: file:// origin, JS enabled, no network.
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'file:///android_asset/www/index.html',
});
const { window } = dom;

// jsdom gaps that CodeMirror touches in a real WebView
window.ResizeObserver = window.ResizeObserver || class { observe(){} unobserve(){} disconnect(){} };
window.requestAnimationFrame = window.requestAnimationFrame || ((cb) => setTimeout(() => cb(Date.now()), 0));
window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){} }));
window.document.createRange = window.document.createRange || (() => ({ getBoundingClientRect: () => ({}) }));

await new Promise((r) => window.addEventListener('load', r, { once: true }));
await new Promise((r) => setTimeout(r, 60));

const errors = [];
window.addEventListener('error', (e) => errors.push(String(e.error || e.message)));

const ReaIde = window.ReaIde;
if (!ReaIde) { console.log('FAIL: window.ReaIde missing'); process.exit(1); }

const steps = [];
const check = (name, fn) => { try { const r = fn(); steps.push([name, r === false ? 'FAIL' : 'ok']); } catch (e) { steps.push([name, 'THROW: ' + e.message]); } };

check('openFile', () => ReaIde.openFile('/home/projects/app.js', 'const a = 1;\nconsole.log(a);\n', null));
check('getContent', () => ReaIde.getContent().includes('console.log'));
check('insertText', () => ReaIde.insertText('// inserted\n'));
check('getContent2', () => ReaIde.getContent().includes('// inserted'));
check('gotoLine', () => ReaIde.gotoLine(2, 3));
check('find', () => ReaIde.find('console', true));
check('setWordWrap', () => ReaIde.setWordWrap(false));
check('setReadOnly', () => ReaIde.setReadOnly(true));
check('setFontSize', () => ReaIde.setFontSize(15));
check('setReadOnlyOff', () => ReaIde.setReadOnly(false));
check('openSecond', () => ReaIde.openFile('/home/projects/style.css', 'body { color: red; }\n', null));
check('debugState', () => JSON.parse(ReaIde.debugState()).tabs.length === 2);
check('closeFile', () => ReaIde.closeFile('/home/projects/style.css'));
check('flush', () => ReaIde.flush());
check('undo', () => ReaIde.undo());
check('redo', () => ReaIde.redo());

for (const [n, r] of steps) console.log(`${r === 'ok' ? '  ✓' : '  ✗'} ${n} ${r === 'ok' ? '' : r}`);
console.log('debugState:', ReaIde.debugState());
console.log('errors:', errors.length ? errors : 'none');
const failed = steps.filter(([, r]) => r !== 'ok').length;
console.log(failed === 0 && errors.length === 0 ? 'ALL EDITOR CHECKS PASSED' : `${failed} failure(s)`);
process.exit(failed === 0 && errors.length === 0 ? 0 : 1);
