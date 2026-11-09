# Arquitetura

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ APK (io.rea.ide)                                                            │
│                                                                             │
│  MainActivity                                                               │
│   ├── Activity bar  [Arquivos] [Editor] [Terminal] [▶ Run] [⋮]              │
│   ├── EditorHost ── WebView ── file:///android_asset/www/index.html         │
│   │                  └── CodeMirror 6 (tabs, syntax, search, undo)          │
│   │                        ▲  window.ReaIde.*                               │
│   │                        ▼  ReaIdeBridge (addJavascriptInterface)         │
│   ├── TerminalHost ── com.termux.view.TerminalView (vendorizado)            │
│   │                  └── TerminalSession ── JNI ── /dev/ptmx ── bash        │
│   └── Drawer ── explorer (RecyclerView) ── Workspace (java.io)              │
│                                                                             │
│  lib/<abi>/libtermux-bootstrap.so   (~40 MB, prefixo já reescrito)          │
│         │                                                                   │
│         └─ BootstrapInstaller ─► /data/data/io.rea.ide/files/usr           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Por que existe o truque do prefixo

Os pacotes do Termux são compilados com `PREFIX=/data/data/com.termux/files/usr` gravado em
`.rodata`, em `DT_RPATH`, em shebangs e em arquivos de configuração. Recompilar centenas de
pacotes por build de CI não é viável.

Solução adotada (mesma técnica de forks sérios):

1. o `applicationId` tem **exatamente 10 caracteres** (`io.rea.ide`), logo
   `/data/data/io.rea.ide/files/usr` tem os mesmos 31 bytes de
   `/data/data/com.termux/files/usr`;
2. `scripts/prepare_bootstrap.py` substitui os bytes **in place** em todos os arquivos do
   bootstrap — deslocamentos ELF, tabelas de seção e shebangs continuam válidos;
3. o pacote reescrito é guardado como `libtermux-bootstrap.so` por ABI dentro de `jniLibs`,
   então o AGP entrega exatamente um arquivo por ABI em `nativeLibraryDir` (legível sem
   permissões, sem descompressão em runtime).

`scripts/patch_bootstrap.py --check` falha o build se alguém mudar o `applicationId` para um
tamanho diferente. Isso já pegou um bug real durante o desenvolvimento (`dev.rea.ide` tem 11
caracteres; `io.rea.ide` tem 10).

## Camadas do código

| Camada | Arquivo | Responsabilidade |
|---|---|---|
| Runtime paths | `runtime/ReaPaths.java` | única fonte de verdade de `$FILES`, `$PREFIX`, `$HOME` |
| Ambiente | `runtime/ShellEnv.java` | env de processo estilo Termux (PATH, TMPDIR, TERM, ANDROID_*) |
| Bootstrap | `runtime/BootstrapInstaller.java` | extrai o `.so`, aplica manifesto (chmod +x), recria symlinks, rename atômico |
| Sessões | `runtime/TerminalManager.java` | ciclo de vida de `TerminalSession`, clipboard, logs |
| Processos | `com.termux.terminal.TerminalProcess` | exec sem pty, saída linha-a-linha para o console |
| Editor | `web/src/editor.mjs` | CodeMirror 6, estado por aba, save com debounce de 220 ms |
| Ponte | `EditorBridge` em `MainActivity` | JS ↔ Java: `onReady`, `onContentChanged`, `onCommand` |
| Arquivos | `Workspace.java` | listar/ler/gravar (write atômico), renomear, excluir |
| UI | `MainActivity`, `FileAdapter` | activity bar, drawer, páginas, diálogos |

## Fluxo de dados do editor

```
digitação ─► CodeMirror state ─► updateListener (220 ms debounce)
        ─► ReaIdeBridge.onContentChanged(path, content)  [JS thread]
        ─► MainActivity.saveFile()  [thread "rea-save"]
        ─► Workspace.write()  (tmp + rename, fsync)
```

Nunca o contrário: o JS não conhece o filesystem, o Java não conhece o modelo do editor. O único
caminho de volta é `ReaIde.openFile()/externalChange()` disparado pelo lado Java (git, formatter,
`rea-open`).

## Páginas, não ViewPager

O editor e o terminal são `FrameLayout`s irmãos com visibilidade alternada. Um `ViewPager` foi
descartado porque o gesto horizontal do carrossel briga com a seleção de texto e com o scroll do
terminal — exatamente o motivo pelo qual IDEs não paginam editor ↔ shell.

## Onde um bug de 1 byte aparece

- se `PREFIX` divergir entre `ReaPaths` e o binário reescrito → `bash: not found`;
- se os symlinks não forem recriados → `bin/sh`, `bin/awk`… somem (são symlinks para
  `dash`/`mawk` no bootstrap);
- se o chmod não for aplicado → `Permission denied` ao executar;
- se `nativeLibraryDir` for lido como asset → o zip fica comprimido e o `ZipInputStream` falha em
  arquivos > 4 KB (por isso `extractNativeLibs=true` + sufixo `.so`).
