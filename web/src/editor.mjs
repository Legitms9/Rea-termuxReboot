/**
 * REA IDE editor surface.
 *
 * Runs inside a WebView over file:///android_asset/www/index.html (single file, no network).
 * The native side talks to it exclusively through `window.ReaIde.*` and receives events through
 * `window.ReaIdeBridge.*` (installed by MainActivity with addJavascriptInterface).
 *
 * Design notes:
 *  - one EditorState per open file, so tabs keep their own undo history, cursor and scroll;
 *  - edits are coalesced (220 ms) before being pushed to the native layer, which owns the disk;
 *  - nothing here does file IO: the native side is the only writer.
 */

import { EditorState, Compartment } from '@codemirror/state';
import {
  EditorView, keymap, highlightActiveLine, highlightActiveLineGutter, drawSelection,
  lineNumbers, highlightSpecialChars, rectangularSelection, crosshairCursor,
} from '@codemirror/view';
import {
  defaultKeymap, history, historyKeymap, indentWithTab, undo, redo,
} from '@codemirror/commands';
import {
  bracketMatching, foldGutter, foldKeymap, indentOnInput, indentUnit,
  syntaxHighlighting, HighlightStyle, StreamLanguage,
} from '@codemirror/language';
import { searchKeymap, highlightSelectionMatches, search } from '@codemirror/search';
import {
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap,
} from '@codemirror/autocomplete';
import { tags as t } from '@lezer/highlight';

import { javascript } from '@codemirror/lang-javascript';
import { html } from '@codemirror/lang-html';
import { css } from '@codemirror/lang-css';
import { json } from '@codemirror/lang-json';
import { python } from '@codemirror/lang-python';
import { java } from '@codemirror/lang-java';
import { markdown } from '@codemirror/lang-markdown';
import { xml } from '@codemirror/lang-xml';
import { sql } from '@codemirror/lang-sql';
import { cpp } from '@codemirror/lang-cpp';
import { rust } from '@codemirror/lang-rust';
import { php } from '@codemirror/lang-php';
import { shell } from '@codemirror/legacy-modes/mode/shell';
import { go } from '@codemirror/legacy-modes/mode/go';
import { ruby } from '@codemirror/legacy-modes/mode/ruby';
import { yaml } from '@codemirror/legacy-modes/mode/yaml';
import { toml } from '@codemirror/legacy-modes/mode/toml';
import { lua } from '@codemirror/legacy-modes/mode/lua';
import { dockerFile } from '@codemirror/legacy-modes/mode/dockerfile';
import { properties } from '@codemirror/legacy-modes/mode/properties';
import { c as cLang } from '@codemirror/legacy-modes/mode/clike';

/* ------------------------------------------------------------------ theme */

const reaTheme = EditorView.theme({
  '&': { color: '#d7dae0', backgroundColor: '#0b0e14' },
  '.cm-content': { caretColor: '#7c5cff' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: '#7c5cff', borderLeftWidth: '2px' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
    { backgroundColor: 'rgba(124,92,255,0.28)' },
  '.cm-activeLine': { backgroundColor: 'rgba(124,92,255,0.06)' },
  '.cm-activeLineGutter': { backgroundColor: 'rgba(124,92,255,0.10)', color: '#a99bff' },
  '.cm-selectionMatch': { backgroundColor: 'rgba(63,185,80,0.18)' },
  '.cm-matchingBracket, &.cm-focused .cm-matchingBracket':
    { backgroundColor: 'rgba(124,92,255,0.30)', outline: 'none' },
  '.cm-tooltip': { backgroundColor: '#11151f', border: '1px solid #1e2430', color: '#d7dae0' },
  '.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: '#2a2140', color: '#fff' },
  '.cm-panels': { backgroundColor: '#0d1117', color: '#d7dae0' },
  '.cm-foldPlaceholder': { backgroundColor: '#1e2430', border: 'none', color: '#8b93a7' },
}, { dark: true });

const reaHighlight = HighlightStyle.define([
  { tag: t.keyword, color: '#c792ea' },
  { tag: [t.name, t.deleted, t.character, t.propertyName, t.macroName], color: '#82aaff' },
  { tag: [t.function(t.variableName), t.labelName], color: '#82aaff' },
  { tag: [t.color, t.constant(t.name), t.standard(t.name)], color: '#f78c6c' },
  { tag: [t.definition(t.name), t.separator], color: '#d7dae0' },
  { tag: [t.typeName, t.className, t.number, t.changed, t.annotation, t.modifier, t.self, t.namespace],
    color: '#ffcb6b' },
  { tag: [t.operator, t.operatorKeyword], color: '#89ddff' },
  { tag: [t.regexp, t.escape, t.special(t.string)], color: '#f78c6c' },
  { tag: [t.string, t.meta], color: '#c3e88d' },
  { tag: [t.bool, t.null, t.atom], color: '#ff9cac' },
  { tag: t.comment, color: '#5c6773', fontStyle: 'italic' },
  { tag: t.heading, color: '#82aaff', fontWeight: 'bold' },
  { tag: t.link, color: '#89ddff', textDecoration: 'underline' },
  { tag: t.invalid, color: '#f85149' },
]);

/* ----------------------------------------------------------- language map */

const LANGS = {
  js: () => javascript(), jsx: () => javascript({ jsx: true }),
  ts: () => javascript({ typescript: true }), tsx: () => javascript({ typescript: true, jsx: true }),
  html: () => html(),
  css: () => css(), scss: () => css(),
  json: () => json(),
  py: () => python(),
  java: () => java(), kotlin: () => java(),
  md: () => markdown(), markdown: () => markdown(),
  xml: () => xml(), svg: () => xml(),
  sql: () => sql(),
  c: () => cLang, cpp: () => cpp(), h: () => cpp(), hpp: () => cpp(),
  rs: () => rust(),
  php: () => php(),
  sh: () => StreamLanguage.define(shell), bash: () => StreamLanguage.define(shell),
  zsh: () => StreamLanguage.define(shell),
  go: () => StreamLanguage.define(go),
  rb: () => StreamLanguage.define(ruby),
  yml: () => StreamLanguage.define(yaml), yaml: () => StreamLanguage.define(yaml),
  toml: () => StreamLanguage.define(toml),
  lua: () => StreamLanguage.define(lua),
  dockerfile: () => StreamLanguage.define(dockerFile),
  ini: () => StreamLanguage.define(properties),
  conf: () => StreamLanguage.define(properties),
  env: () => StreamLanguage.define(properties),
  txt: () => [],
};

export function detectLanguage(path) {
  if (!path) return 'txt';
  const base = path.split('/').pop().toLowerCase();
  if (base === 'dockerfile' || base.startsWith('dockerfile.')) return 'dockerfile';
  if (base === 'makefile') return 'sh';
  const dot = base.lastIndexOf('.');
  if (dot < 0) return 'txt';
  const ext = base.slice(dot + 1);
  return LANGS[ext] ? ext : 'txt';
}

const langConf = new Compartment();
const readOnlyConf = new Compartment();
const wrapConf = new Compartment();

/* ------------------------------------------------------------------- state */

const tabs = [];            // [{ path, name, state, dirty, view? }]
let active = null;          // tab object
let view = null;            // single EditorView, state swapped per tab
let saveTimer = null;
let wrapEnabled = true;

const els = {};

/* --------------------------------------------------------------------- api */

function emitSave(path, text) {
  try { window.ReaIdeBridge && window.ReaIdeBridge.onContentChanged(path, text); } catch (e) { /* ignore */ }
}

function scheduleSave() {
  if (!active) return;
  active.dirty = true;
  updateStatus();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => emitSave(active.path, active.state.doc.toString()), 220);
}

function updateStatus() {
  if (!els.pos) return;
  const sel = active ? active.state.selection.main : null;
  if (active) {
    const line = active.state.doc.lineAt(sel.head);
    els.path.textContent = active.path;
    els.pos.textContent = `Ln ${line.number}, Col ${sel.head - line.from + 1}`;
    els.lang.textContent = detectLanguage(active.path);
    els.dirty.textContent = active.dirty ? '●' : '';
    els.dirty.classList.toggle('on', active.dirty);
  } else {
    els.path.textContent = 'sem arquivo';
    els.pos.textContent = 'Ln 1, Col 1';
    els.lang.textContent = '—';
    els.dirty.classList.remove('on');
  }
  renderTabs();
}

function renderTabs() {
  const bar = els.tabbar;
  if (!bar) return;
  bar.textContent = '';
  for (const tab of tabs) {
    const el = document.createElement('div');
    el.className = 'tab' + (tab === active ? ' active' : '');
    const name = document.createElement('span');
    name.className = 'tab-name';
    name.textContent = tab.name;
    el.appendChild(name);
    if (tab.dirty) {
      const dot = document.createElement('span');
      dot.className = 'tab-dot';
      dot.textContent = '●';
      el.appendChild(dot);
    }
    const close = document.createElement('span');
    close.className = 'tab-close';
    close.textContent = '×';
    close.addEventListener('click', (ev) => {
      ev.stopPropagation();
      window.ReaIde.closeFile(tab.path);
    });
    el.appendChild(close);
    el.addEventListener('click', () => window.ReaIde.activateFile(tab.path));
    bar.appendChild(el);
  }
  if (active) {
    const at = tabs.indexOf(active);
    const child = bar.children[at];
    if (child && child.scrollIntoView) child.scrollIntoView({ inline: 'nearest', block: 'nearest' });
  }
}

function docExtensions(extra) {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightSpecialChars(),
    history(),
    foldGutter(),
    drawSelection(),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    autocompletion({ activateOnTyping: true, maxRenderedOptions: 8 }),
    highlightSelectionMatches(),
    rectangularSelection(),
    crosshairCursor(),
    highlightActiveLine(),
    search({ top: false }),
    EditorState.allowMultipleSelections.of(true),
    indentUnit.of('  '),
    syntaxHighlighting(reaHighlight),
    reaTheme,
    keymap.of([
      { key: 'Mod-s', preventDefault: true, run: () => { flush(); return true; } },
      ...closeBracketsKeymap,
      ...defaultKeymap,
      ...searchKeymap,
      ...historyKeymap,
      ...foldKeymap,
      ...completionKeymap,
      indentWithTab,
    ]),
    langConf.of([]),
    readOnlyConf.of(EditorState.readOnly.of(false)),
    wrapConf.of(EditorView.lineWrapping),
    EditorView.updateListener.of((u) => {
      // Keep the per-tab EditorState authoritative: the view is swapped between tabs, so
      // anything that reads active.state (save, close, getContent) must see the live state.
      if (active) active.state = u.state;
      if (u.docChanged || u.selectionSet) {
        if (u.docChanged) scheduleSave();
        updateStatus();
      }
    }),
  ];
}

function flush() {
  clearTimeout(saveTimer);
  if (active && active.dirty) emitSave(active.path, active.state.doc.toString());
}

/* ------------------------------------------------------------ public API */

const ReaIde = {
  /** Native -> web: open (or focus) a file with its content. */
  openFile(path, content, languageId) {
    let tab = tabs.find((t) => t.path === path);
    if (!tab) {
      const lang = LANGS[languageId] || LANGS[detectLanguage(path)];
      tab = {
        path,
        name: path.split('/').pop(),
        dirty: false,
        state: EditorState.create({
          doc: content ?? '',
          extensions: docExtensions(lang ? lang() : []),
        }),
      };
      tabs.push(tab);
    }
    ReaIde.activateFile(path);
    return true;
  },

  activateFile(path) {
    const tab = tabs.find((t) => t.path === path);
    if (!tab) return false;
    flush();
    active = tab;
    if (!view) view = new EditorView({ state: tab.state, parent: els.editor });
    else view.setState(tab.state);
    tab.state = view.state;
    els.welcome.hidden = true;
    els.editor.hidden = false;
    updateStatus();
    view.focus();
    return true;
  },

  closeFile(path) {
    const i = tabs.findIndex((t) => t.path === path);
    if (i < 0) return false;
    const tab = tabs[i];
    if (tab.dirty) emitSave(tab.path, tab.state.doc.toString());
    tabs.splice(i, 1);
    if (active === tab) {
      active = tabs[Math.max(0, i - 1)] || null;
      if (active) {
        view.setState(active.state);
        els.welcome.hidden = true;
        els.editor.hidden = false;
      } else {
        els.editor.hidden = true;
        els.welcome.hidden = false;
      }
    }
    updateStatus();
    return true;
  },

  /** Native -> web: the file changed on disk (git pull, formatter, external script). */
  externalChange(path, content) {
    const tab = tabs.find((t) => t.path === path);
    if (!tab) return false;
    if (tab.state.doc.toString() === content) return true;
    const cursor = tab.state.selection.main.head;
    const lang = LANGS[detectLanguage(path)];
    tab.state = EditorState.create({
      doc: content,
      selection: { anchor: Math.min(cursor, content.length) },
      extensions: docExtensions(lang ? lang() : []),
    });
    tab.dirty = false;
    if (active === tab && view) view.setState(tab.state);
    updateStatus();
    return true;
  },

  setReadOnly(flag) {
    if (!view) return false;
    view.dispatch({ effects: readOnlyConf.reconfigure(EditorState.readOnly.of(!!flag)) });
    return true;
  },

  setWordWrap(flag) {
    wrapEnabled = !!flag;
    if (!view) return false;
    view.dispatch({ effects: wrapConf.reconfigure(flag ? EditorView.lineWrapping : []) });
    return true;
  },

  /** Insert text at the cursor (used by the extra-keys row and by snippets). */
  insertText(text) {
    if (!view) return false;
    view.dispatch(view.state.replaceSelection(text));
    view.focus();
    return true;
  },

  /** Goto line/column, 1-based. Used for "jump to error" from the console. */
  gotoLine(line, column) {
    if (!view) return false;
    const doc = view.state.doc;
    const target = doc.line(Math.min(Math.max(1, line), doc.lines));
    const pos = Math.min(target.from + Math.max(0, (column || 1) - 1), target.to);
    view.dispatch({ selection: { anchor: pos }, scrollIntoView: true });
    view.focus();
    return true;
  },

  getContent() {
    if (view) return view.state.doc.toString();
    return active ? active.state.doc.toString() : null;
  },

  /** Native -> web: caret moved by the on-screen key row. */
  moveCursor(dir) {
    if (!view) return false;
    const map = { up: 'ArrowUp', down: 'ArrowDown', left: 'ArrowLeft', right: 'ArrowRight' };
    const key = map[dir];
    if (!key) return false;
    view.focus();
    view.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    return true;
  },

  flush() { flush(); return true; },

  undo() { if (!view) return false; undo(view); return true; },
  redo() { if (!view) return false; redo(view); return true; },

  find(term, forward = true) {
    if (!view || !term) return false;
    const q = term;
    const sel = view.state.selection.main;
    const text = view.state.doc.toString();
    let idx;
    if (forward) {
      idx = text.indexOf(q, sel.to);
      if (idx < 0) idx = text.indexOf(q, 0);
    } else {
      idx = text.lastIndexOf(q, Math.max(0, sel.from - 1));
      if (idx < 0) idx = text.lastIndexOf(q);
    }
    if (idx < 0) return false;
    view.dispatch({ selection: { anchor: idx, head: idx + q.length }, scrollIntoView: true });
    return true;
  },

  setFontSize(px) {
    if (!els.editor) return false;
    els.editor.style.setProperty('--editor-font', px + 'px');
    const scroller = els.editor.querySelector('.cm-scroller');
    if (scroller) scroller.style.fontSize = px + 'px';
    return true;
  },

  /** Diagnostics hook: returns basic state for debugging from Java. */
  debugState() {
    return JSON.stringify({ tabs: tabs.map((t) => ({ p: t.path, d: t.dirty })), active: active?.path ?? null });
  },
};

window.ReaIde = ReaIde;

/* ------------------------------------------------------------------ boot */

function boot() {
  els.tabbar = document.getElementById('tabbar');
  els.editor = document.getElementById('editor');
  els.welcome = document.getElementById('welcome');
  els.path = document.getElementById('status-path');
  els.pos = document.getElementById('status-pos');
  els.lang = document.getElementById('status-lang');
  els.dirty = document.getElementById('status-dirty');
  els.searchbar = document.getElementById('searchbar');
  els.searchInput = document.getElementById('search-input');

  els.editor.hidden = true;

  document.querySelectorAll('.welcome-actions button').forEach((b) => {
    b.addEventListener('click', () => {
      try { window.ReaIdeBridge && window.ReaIdeBridge.onCommand(b.dataset.action); } catch (e) { /* ignore */ }
    });
  });

  const closeSearch = () => { els.searchbar.hidden = true; };
  document.getElementById('search-next').addEventListener('click', () => ReaIde.find(els.searchInput.value, true));
  document.getElementById('search-prev').addEventListener('click', () => ReaIde.find(els.searchInput.value, false));
  document.getElementById('search-close').addEventListener('click', closeSearch);
  els.searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') ReaIde.find(els.searchInput.value, true);
  });

  // Prevent the WebView from rubber-banding / zooming inside the editor.
  document.addEventListener('gesturestart', (e) => e.preventDefault());

  updateStatus();
  try { window.ReaIdeBridge && window.ReaIdeBridge.onReady(); } catch (e) { /* ignore */ }
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
