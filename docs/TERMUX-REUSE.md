# O que reutilizamos do Termux (e o que reescrevemos)

Pedido original: *"vamos reutilizar do código de construção do termux que tem o código aberto para
estruturar o nosso app"*. Isto é o mapa honesto dessa reutilização.

## Licenças em jogo

| Componente | Licença | Usamos? |
|---|---|---|
| `termux/terminal-emulator` | **Apache-2.0** (derivado de jackpal/Android-Terminal-Emulator) | ✅ vendorizado |
| `termux/terminal-view` | **Apache-2.0** | ✅ vendorizado |
| `termux/termux-app` | **GPLv3** | ❌ não copiado |
| `termux/termux-shared` | **GPLv3** | ❌ não copiado |
| bootstrap (`termux-packages`) | GPLv2 (pacotes individuais têm suas licenças) | ✅ baixado no build, não redistribuído no repositório |
| CodeMirror 6 | MIT | ✅ `web/` |

O APK final contém código Apache-2.0 + MIT + um bootstrap binário instalado em runtime. Nenhum
arquivo GPLv3 do `termux-app` foi copiado para este repositório, então o app não é derivado dele.

## Copiado (byte a byte, Apache-2.0)

`vendor/termux/terminal-emulator/src/main/java/com/termux/terminal/`
- `TerminalEmulator.java` (2.605 linhas, parser VT/xterm completo)
- `TerminalBuffer.java`, `TerminalRow.java`, `TerminalColors.java`, `TerminalColorScheme.java`
- `ByteQueue.java`, `TextStyle.java`, `WcWidth.java`, `KeyHandler.java`, `Logger.java`
- `TerminalSession.java` (threads de leitura/escrita/waiter da pty), `TerminalOutput.java`,
  `TerminalSessionClient.java`

`vendor/termux/terminal-view/src/main/java/com/termux/view/`
- `TerminalView.java` (1.476 linhas: Canvas, IME, gestos, autofill), `TerminalRenderer.java`
- `GestureAndScaleRecognizer.java`, `textselection/*` e `res/drawable/text_select_handle_*`

`vendor/termux/terminal-emulator/src/main/jni/termux.c` — lógica de `create_subprocess`
(`forkpty`-manual com `openpty`, `TIOCSWINSZ`, `waitpid`) intacta.

## Adaptado (marcado com "REA" nos arquivos)

| Arquivo | Mudança | Motivo |
|---|---|---|
| `JNI.java` | `RegisterNatives` em vez de símbolos `Java_com_termux_*` | manter o core renomeável |
| `termux.c` | funções `static` + registro dinâmico; `createPipeProcess()` novo | console de build sem pty |
| `TerminalProcess.java` | arquivo novo | streaming de saída para o console |
| `build.gradle` dos dois módulos | AGP 8, `namespace`, Java 11 | toolchain moderna |

## Reescrito (lido como referência, sem copiar)

| termux-app / termux-shared | Nosso equivalente | Por quê |
|---|---|---|
| `TermuxShellUtils.buildEnvironment()` | `runtime/ShellEnv.java` | precisamos do mesmo env, mas apontando para o nosso prefixo e sem o `com.termux` hard-coded |
| `TermuxInstaller.setupBootstrapIfNeeded()` | `runtime/BootstrapInstaller.java` | mesmo pipeline (staging → chmod → symlinks → rename), mas lendo de `nativeLibraryDir` em vez de uma lib `.so` gerada por assembler, e com manifesto JSON de permissões |
| `TermuxService` (serviço + wake locks + notificações) | não temos | o IDE mantém a sessão viva enquanto está em foreground (`FLAG_KEEP_SCREEN_ON`); um `TermuxService` completo fica para a v2 |
| `TermuxTerminalSessionClient` | `runtime/TerminalManager.java` | ~250 linhas em vez de ~900, sem integração de plugins |
| `TermuxTerminalViewClient` | `MainActivity implements TerminalViewClient` | sem "virtual keys"/estilos do Termux |
| `TermuxConstants` | `runtime/ReaPaths.java` | 40 caminhos → 12, todos derivados de um só `applicationId` |

## O que ainda falta para paridade com o Termux (roadmap)

- [ ] serviço em background com notificação persistente (sessões sobrevivem ao app em segundo plano)
- [ ] `termux-api` (câmera, sensores, clipboard, notificações) — precisa do app Termux:API
- [ ] teclado extra completo (setas, `Ctrl+C`, F1–F12) com estado por sessão
- [ ] theme switching do terminal em runtime
- [ ] instalador de pacotes via dialog (`pkg install …` com progresso)
