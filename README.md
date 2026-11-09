# REA · Termux IDE

Um editor de código + terminal Linux para Android, empacotado como **um único APK** e compilado
por **GitHub Actions** com artefato publicado.

- **Terminal Linux real**: bootstrap do Termux (bash, apt, python, node, clang…) rodando em
  `$PREFIX`, com pty de verdade — não é um emulador de brinquedo.
- **Editor de verdade**: CodeMirror 6 (MIT) em WebView, com syntax highlight para ~30 linguagens,
  abas, busca, undo por aba, salvamento com debounce.
- **Zero dependência de apps externos**: o bootstrap mora dentro do APK.

```
scripts/build_cloudshell.sh       build em qualquer VM Linux, sem CI (Cloud Shell, Codespaces…)
.gitlab-ci.yml / codemagic.yaml   CIs alternativas, mesmo pipeline: testes → bootstrap → APK
azure-pipelines.yml
.github/workflows/build-apk.yml   pipeline de referência (guard → web → bootstrap → APK)
docker/Dockerfile                 build reprodutível sem SDK local
```

## Gerar o APK (sem GitHub Actions)

O Actions desta conta está desabilitado, então o build roda em outra máquina gratuita. Guia
completo com custo e passo a passo: **[`docs/COMPILAR-SEM-ACTIONS.md`](docs/COMPILAR-SEM-ACTIONS.md)**.

**Mais rápido (2 minutos, nada para configurar)** — Google Cloud Shell:

```sh
curl -fsSL https://raw.githubusercontent.com/Legitms9/Rea-termuxReboot/arena/65202ee3-rea-termuxreboot/scripts/build_cloudshell.sh | bash
# no fim: ~/rea-apk/rea-termux-ide-*.apk  (⋮ → Download)
```

**Automático a cada push** — escolha um:

| CI | Arquivo já no repo | Grátis |
|---|---|---|
| GitLab CI (espelha o GitHub) | [`.gitlab-ci.yml`](.gitlab-ci.yml) | 400 min/mês |
| Codemagic (conecta no GitHub) | [`codemagic.yaml`](codemagic.yaml) | 500 min/mês |
| Azure Pipelines | [`azure-pipelines.yml`](azure-pipelines.yml) | 1.800 min/mês |
| GitHub Actions (quando religar) | [`.github/workflows/build-apk.yml`](.github/workflows/build-apk.yml) | 2.000 min/mês |

Depois: `adb install -r rea-termux-ide-0.1.0-debug-arm64-v8a.apk`.

Não há APK commitado neste repositório — ele é sempre gerado por um runner.

## Build local

Pré-requisitos: JDK 17, Android SDK 34 + NDK 26.1.10909125, Node 20+, Python 3.11+, `gh`
autenticado (para baixar o bootstrap).

```sh
# 1. bootstrap do Termux com o prefixo reescrito (~40 MB por ABI)
python3 scripts/prepare_bootstrap.py \
  --release "bootstrap-2026.11.08-r1+apt.android-7" \
  --app-id io.rea.ide --abis arm64-v8a \
  --out-dir app/src/main/jniLibs --cache-dir build/bootstrap-cache

# 2. editor web
cd web && npm ci && npm run build && cd ..

# 3. APK
./gradlew assembleDebug -Prea.webPrefetched=true
# app/build/outputs/apk/debug/rea-termux-ide-0.1.0-debug-arm64-v8a.apk
```

Sem Android SDK na máquina? Use o container:

```sh
docker build -f docker/Dockerfile -t rea-ide-build .
mkdir -p out && docker run --rm -v "$PWD/out:/out" -v "$PWD:/src" -w /src \
  -e GH_TOKEN="$(gh auth token)" rea-ide-build
```

Só quer ver a UI do editor, sem Android? `cd web && npm run build && npm run preview` →
<http://localhost:8080/> (o harness `web/dev/preview.html` simula a ponte nativa).

## Como funciona (o pulo do gato)

Os binários do Termux têm `/data/data/com.termux/files/usr` compilado dentro deles. Em vez de
recompilar centenas de pacotes, o `applicationId` deste app tem **exatamente o mesmo tamanho**
(`io.rea.ide`, 10 caracteres), então o prefixo pode ser substituído **byte a byte, no lugar**:

```
/data/data/com.termux/files/usr    (31 bytes)
/data/data/io.rea.ide/files/usr    (31 bytes)
```

`scripts/prepare_bootstrap.py` baixa o bootstrap oficial, confere o SHA-256 publicado no release,
reescreve os bytes em todos os arquivos, gera um manifesto de permissões e embrulha tudo como
`libtermux-bootstrap.so` por ABI. O app extrai esse arquivo de `nativeLibraryDir` na primeira
execução. Se alguém mudar o `applicationId`, `scripts/patch_bootstrap.py --check` **quebra o
build** antes de gerar um APK quebrado.

Detalhes: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## O que é reutilizado do Termux

`terminal-emulator` e `terminal-view` (Apache-2.0) são vendorizados e ficaram byte a byte iguais
ao upstream, exceto o glue JNI. Nada de `termux-app`/`termux-shared` (GPLv3) foi copiado.
Mapa completo: [`docs/TERMUX-REUSE.md`](docs/TERMUX-REUSE.md).

## Testes

| O que | Comando | Cobre |
|---|---|---|
| patcher do bootstrap | `python3 scripts/test_prepare_bootstrap.py` | patch in place, ELF intacto, symlinks do upstream, manifesto de permissões, repack |
| invariante do app id | `python3 scripts/patch_bootstrap.py --check` | prefixo de mesmo tamanho |
| editor (DOM real) | `cd web && npm test` | abrir/editar/achar/undo por aba, autosave, close |
| filtro ANSI | `cd web && npm test` | equivalência com `LineFilterTest` (JVM) |
| JVM | `./gradlew test` | `LineFilterTest` |

## Estrutura

```
app/                      módulo Android (io.rea.ide)
  src/main/java/io/rea/ide/
    MainActivity.java     activity bar, páginas, drawer, ponte JS
    Workspace.java        arquivos (write atômico)
    runtime/              ReaPaths, ShellEnv, BootstrapInstaller, TerminalManager
  src/main/res/           tema escuro OLED, layouts
vendor/termux/            terminal-emulator + terminal-view (Apache-2.0)
web/                      editor CodeMirror 6 (esbuild, bundle único, sem rede)
  src/editor.mjs          API window.ReaIde
  dev/preview.html        harness de preview com bridge mockado
  test/editor.test.mjs    smoke test em jsdom (roda no CI)
scripts/                  prepare_bootstrap.py, patch_bootstrap.py, publish_bootstrap.py
                          + test_prepare_bootstrap.py
docker/                   Dockerfile + entrypoint para build sem SDK local
docs/                     ARCHITECTURE, TERMUX-REUSE, REA-REVERSE-ENGINEERING
```

## Estado atual / roadmap

Funciona: editor com abas e autosave, explorer com criar/renomear/excluir, terminal com múltiplas
sessões, Ctrl/Alt/ESC/TAB/setas, `▶ Run` (http.server, node, script, comando livre), abrir arquivo
por `VIEW` intent.

Próximo: serviço em background (sessões sobrevivem ao app), `termux-api`, teclado extra completo,
instalador de pacotes com UI, snippets/LSP. Ver o fim de `docs/TERMUX-REUSE.md`.

## Licença

Código próprio: MIT. Módulos vendorizados mantêm suas licenças (Apache-2.0); o bootstrap do
Termux não é redistribuído neste repositório.
