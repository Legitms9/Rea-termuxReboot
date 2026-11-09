# REA: engenharia reversa usada neste projeto

O passo 1 do briefing foi instalar o [REA](https://rea.tools/) para inspecionar interfaces e
reconstruir a estrutura de UI/UX. Isto é o que foi feito e o que foi aprendido.

## Instalação

```sh
npx rea-agents@latest setup      # registra REA no coding agent + instala o skill
npx rea-agents@latest doctor     # confere dependências e provedores
```

Versão usada: **6.8.0** (`rea-agents`, `io.github.morluto/rea`).

O `doctor` deste ambiente reporta duas coisas que valem registro:

1. `Install Node.js 22.x (>=22.23.4)` — o sandbox tinha 22.22.3, abaixo do mínimo exigido pelo
   REA 6.8 para o próprio runtime. Não bloqueia a análise estática que fizemos (leitura de
   bundle/JS/HTTP), mas bloqueia os provedores nativos.
2. Provedores nativos ausentes (`ghidra`, `ida`, `jadx`, `kuna`) — `classification:
   missing_analysis_engine`. Para inspecionar o APK do Cursor/VS Code numa máquina de dev:

   ```sh
   export REA_JADX_MCP_JAR=/caminho/jadx-headless-mcp-0.7.1.jar   # REA não baixa por você
   export GHIDRA_INSTALL_DIR=/opt/ghidra_12.1
   npx rea-agents doctor
   ```

## O que foi inspecionado e o que saiu disso

| Alvo | Pergunta | Achado que virou código |
|---|---|---|
| `termux-app` (fonte aberta, então leitura direta em vez de binário) | como o prefixo é instalado e usado? | `BootstrapInstaller` reproduz o pipeline staging→chmod→symlinks→rename; `ShellEnv` reproduz o env |
| bootstrap `bootstrap-aarch64.zip` | o prefixo está mesmo gravado nos binários? | sim: `SYMLINKS.txt`, `bin/*`, `lib/python*/…` — daí o patch de bytes de mesmo tamanho |
| UI de IDEs baseadas em CodeMirror (VS Code web, Cursor, CodePen) | qual a estrutura de UI/UX mínima que funciona no celular? | activity bar (3 abas + Run + ⋮), drawer de explorer, status bar com `Ln/Col/lang/dirty`, tab bar com dot de arquivo sujo, painel de busca flutuante |
| CodePen | por que o preview é instantâneo? | estado do documento em memória + salvamento debounced (adotamos 220 ms), nunca I/O no keystroke |

## Como reproduzir a análise da UI (numa máquina com Node ≥ 22.23.4)

```sh
# 1. abrir o app alvo com depuração remota e apontar o REA para o endpoint
npx rea-agents inspect browser --url http://127.0.0.1:9222

# 2. pedir ao agente a pergunta específica, não "analise o app"
#    ex.: "Quais elementos de UI existem na barra lateral e qual o atalho de cada um?"

# 3. para APK: extrair e apontar o jadx
unzip -o app-release.apk classes.dex -d /tmp/apk
REA_JADX_MCP_JAR=/opt/jadx-headless-mcp.jar npx rea-agents inspect apk /tmp/apk
```

## Estrutura de UI que reconstruímos

```
┌ ◆ REA │ Arquivos │ Editor │ Terminal │              ▶ Run  ⋮ ┐   <- activity bar (44dp)
├─────────────────────────────────────────────────────────────┤
│ tab bar:  app.js ●  │  style.css  │  ×                     │   <- só quando há arquivos
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  editor (CodeMirror 6)            ou     terminal (pty)      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ Ln 12, Col 4 │ javascript │ ●                               │   <- status bar
├─────────────────────────────────────────────────────────────┤
│ ~/projects/hello-web                              pronto     │   <- breadcrumb (30dp)
└─────────────────────────────────────────────────────────────┘
   drawer (300dp): EXPLORER · ~/projects · lista · ações
```

O preview navegável dessa UI está em `web/dev/preview.html` (mock do bridge nativo): rode
`cd web && npm run build && npm run preview` e abra `http://localhost:8080/`.
