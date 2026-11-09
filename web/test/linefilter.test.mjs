#!/usr/bin/env node
/**
 * LineFilter (io.rea.ide.LineFilter) parity test.
 *
 * The Java implementation cannot run in this environment, so the state machine is
 * transliterated here to prove the algorithm before it reaches the device. The Java unit test
 * (app/src/test/java/io/rea/ide/LineFilterTest.java) asserts the same cases on the JVM in CI.
 */
const cases = [
  ['\u001b[0;32mok\u001b[0m', 'ok'],
  ['a\u001b[K\u001b[1;1Hb', 'ab'],
  ['\u001b]0;title\u0007x', 'x'],
  ['\u001b]0;title\u001b\\x', 'x'],
  ['a\tb\r', 'a\tb'],
  ['done\u001b[', 'done'],
  ['done\u001b', 'done'],
  ['npm test 1/2 passed', 'npm test 1/2 passed'],
  ['\u001b[38;5;208mwarning\u001b[0m: unused var', 'warning: unused var'],
];

/** Mirror of LineFilter.stripAnsi — same control flow, same edge cases. */
export function stripAnsi(input) {
  if (!input || !input.length) return '';
  let out = '';
  let i = 0;
  const n = input.length;
  while (i < n) {
    const c = input.charCodeAt(i);
    if (c !== 0x1b) {
      if (c < 0x20 && c !== 0x09) { i++; continue; }
      out += input[i];
      i++;
      continue;
    }
    i++;
    if (i >= n) break;
    const kind = input[i];
    if (kind === '[') {
      i++;
      while (i < n) {
        const ch = input.charCodeAt(i);
        i++;
        if (ch >= 0x40 && ch <= 0x7e) break;
      }
    } else if (kind === ']') {
      i++;
      while (i < n) {
        const ch = input.charCodeAt(i);
        if (ch === 0x07) { i++; break; }
        if (ch === 0x1b && i + 1 < n && input[i + 1] === '\\') { i += 2; break; }
        i++;
      }
    } else if (kind === '(' || kind === ')') {
      i += 2;
    } else {
      i++;
    }
  }
  return out;
}

let failed = 0;
for (const [input, expected] of cases) {
  const got = stripAnsi(input);
  if (got !== expected) {
    failed++;
    console.log(`  ✗ ${JSON.stringify(input)} => ${JSON.stringify(got)} (esperado ${JSON.stringify(expected)})`);
  }
}
console.log(`line filter: ${cases.length - failed}/${cases.length} casos`);
process.exit(failed ? 1 : 0);
