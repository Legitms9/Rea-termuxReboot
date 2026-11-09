# Vendored Termux modules

These two Gradle modules are copied from [termux/termux-app](https://github.com/termux/termux-app)
`v0.118.3` and are **not** modified except where noted below.

| Directory | Upstream | License |
|---|---|---|
| `terminal-emulator/` | `terminal-emulator/` | Apache-2.0 (derived from jackpal/Android-Terminal-Emulator) |
| `terminal-view/` | `terminal-view/` | Apache-2.0 |

The application module (`termux-app/`) and `termux-shared/` are **not** vendored. `termux-app` is
GPLv3 and we only re-implemented the small pieces we need (environment construction, bootstrap
extraction) from scratch, so the APK as a whole is not a derivative of GPL code. See
`TERMUX-APP-LICENSE.md` for the upstream license text and `../docs/TERMUX-REUSE.md` for the
detail of what was copied, what was rewritten and why.

## Local modifications

1. **`terminal-emulator/.../JNI.java`** — `System.loadLibrary("termux")` now calls
   `nativeRegister(JNI.class)` and the four pty entry points are bound with `RegisterNatives`
   instead of relying on `Java_com_termux_terminal_JNI_*` symbol names. This keeps the native
   glue rename-safe if the module is ever repackaged.
2. **`terminal-emulator/src/main/jni/termux.c`** — the upstream functions are unchanged; their
   exported names were made `static` and re-bound from `Java_com_termux_terminal_JNI_nativeRegister`
   (the single symbol whose name still matters). One **additional** function,
   `createPipeProcess`, was added: it forks a child with stdout/stderr on a pipe and no pty, for
   the IDE's build/run console.
3. **`terminal-emulator/.../TerminalProcess.java`** — new file, uses (2) to stream line-oriented
   command output into the IDE console.
4. **`build.gradle` (both modules)** — rewritten for AGP 8 (`namespace`, `compileSdk` from the root
   project, Java 11, no `maven-publish`).

Everything else — the VT/xterm parser (`TerminalEmulator`, 2.6k lines), the canvas renderer, the
IME/text-selection plumbing, `KeyHandler`, `WcWidth` — is byte-for-byte upstream.

## Why not just depend on the published artifacts?

Termux publishes the libraries to JitPack only for the `com.termux` app id and with an AGP 4
build. We need AGP 8, a custom app id and one extra native function, so vendoring is both simpler
and more honest about what is actually reused.
