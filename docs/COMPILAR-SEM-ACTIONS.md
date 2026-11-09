# Compilar o APK sem o GitHub Actions

O Actions está desabilitado na conta, então nada é compilado no `github.com`. Todas as opções
abaixo usam **máquina de outra pessoa** — nenhuma compila no seu celular ou PC.

Escolha uma. Todas partem do mesmo repo e do mesmo `scripts/build_cloudshell.sh` (que é a
sequência: testes → web → bootstrap → gradle). O que muda é só "quem aperta o botão".

| # | Opção | Esforço | Custo | Automático a cada push? | Onde pega o APK |
|---|---|---|---|---|---|
| 1 | **Google Cloud Shell** (script) | 2 min | grátis | ❌ (manual) | `~/rea-apk/*.apk` → download |
| 2 | **GitLab CI** (espelho do repo) | 15 min, uma vez | 400 min/mês grátis | ✅ | artefato do pipeline |
| 3 | **Codemagic** (conecta no GitHub) | 5 min, uma vez | 500 min/mês grátis | ✅ | artifacts do build |
| 4 | **Azure Pipelines** | 10 min, uma vez | 1.800 min/mês grátis (repo público) | ✅ | artifact do build |
| 5 | **Codespaces / Gitpod** | 2 min | 60 h / 50 h por mês | ❌ | download do arquivo |
| 6 | **Docker** em qualquer máquina | 5 min | o da máquina | ❌ | `out/*.apk` |

> Não recomendo "compilar no Termux do próprio celular": exige ~10 GB, JDK + SDK + NDK, e leva
> 20–40 min em um aparelho de 8 GB. Funciona (`bash scripts/build_cloudshell.sh` dentro do
> Termux), mas é a pior experiência — e é justamente o que você pediu para evitar.

---

## 1. Google Cloud Shell — o mais rápido, zero configuração

<https://shell.cloud.google.com> (precisa de conta Google; VM Linux efêmera, grátis, 5 GB).

```sh
curl -fsSL https://raw.githubusercontent.com/Legitms9/Rea-termuxReboot/arena/65202ee3-rea-termuxreboot/scripts/build_cloudshell.sh | bash
```

Em ~10 min (download do bootstrap + Gradle) ele imprime:

```
APK pronto
  arquivo : ~/rea-apk/rea-termux-ide-0.1.0-debug-arm64-v8a.apk
  tamanho : ~55M
  sha256  : ...
```

Baixe com **⋮ → Download** informando o caminho, ou:

```sh
cd ~/rea-apk && python3 -m http.server 8000     # depois: Web preview → porta 8000
```

Cuidado: a sessão do Cloud Shell expira (~20 min ociosa). Se cair, rode de novo — o cache do
bootstrap fica em `build/bootstrap-cache` dentro do clone temporário, que também se perde.

## 2. GitLab CI — build automático a cada push, de graça

O `.gitlab-ci.yml` já está no repo. Dois caminhos:

**a) Espelho (recomendado: você continua no GitHub)**

1. gitlab.com → *New project* → *Import project* → **GitHub** → autorize → escolha
   `Legitms9/Rea-termuxReboot`.
2. No projeto importado: *Settings → Repository → Mirroring repositories* → **Pull**,
   URL `https://github.com/Legitms9/Rea-termuxReboot.git`, a cada 1 hora.
3. *Build → Pipelines → Run pipeline* na branch. O job `build:apk` gera
   `out/rea-termux-ide-*.apk` em *Browse artifacts*.

**b) Push direto para o GitLab** (um remote a mais):

```sh
git remote add gitlab git@gitlab.com:SEU_USUARIO/Rea-termuxReboot.git
git push gitlab arena/65202ee3-rea-termuxreboot
```

Runners: use os compartilhados do gitlab.com (padrão). A imagem `ghcr.io/cirruslabs/android-sdk:34`
já traz SDK 34 + NDK, então o job é curto.

## 3. Codemagic — já conectado ✔

App: [`codemagic.io/app/6af11769a4abdfa900b420cb`](https://codemagic.io/app/6af11769a4abdfa900b420cb/settings)

O `codemagic.yaml` está na branch `arena/65202ee3-rea-termuxreboot` (vai para a `main` no merge
do PR #1). Então, no **primeiro** build, escolha essa branch explicitamente — senão a Codemagic
não acha a configuração:

```
Codemagic → app → Start new build
  ├─ Branch: arena/65202ee3-rea-termuxreboot     ← não deixe "main"
  └─ Workflow: android-apk
```

Ou, se preferir que o build de `main` funcione já: mergeie o PR #1.

O que o workflow faz (9 passos): diagnóstico do ambiente → invariante do app id → testes do
patcher → editor web + testes → download/verificação do bootstrap → **validação do prefixo dentro
de `bin/bash`** → SDK/NDK → `assembleDebug` → conferência do conteúdo do APK (`libtermux*.so` e
`assets/www/index.html` presentes) → artefato + `SHA256SUMS.txt`.

Se algo falhar, o passo onde parou já diz o que é. Os três erros mais prováveis na primeira vez:

| Passo que falha | Causa | O que fazer |
|---|---|---|
| `bootstrap do Termux` | Codemagic sem `gh` e download do GitHub bloqueado | adicione a variável `REA_BOOTSTRAP_PROXY` = `https://ghproxy.net/https://github.com` em *Environment variables* |
| `Android SDK / NDK` | imagem sem NDK 26.1 | o passo instala; se falhar, troque `instance_type` para `mac_mini_m2` (também tem free tier) |
| `build APK` | erro de compilação Java/C | me manda o trecho — é a primeira compilação real do projeto |

### Configurações recomendadas em *Settings*

- **Build triggers**: já vêm do `triggering:` do YAML (push em `main` e `arena/*`).
- **Environment variables**: nenhuma obrigatória. Opcionais: `REA_BOOTSTRAP_PROXY`,
  `CM_EMAIL_RECIPIENT` (para notificação por e-mail).
- **Code signing (Android)**: **não é necessário** para o APK debug. Só configure se quiser
  release assinado; nesse caso, o `app/build.gradle` já aceita
  `REA_KEYSTORE_FILE`/`REA_KEYSTORE_PASSWORD`/`REA_KEY_ALIAS`/`REA_KEY_PASSWORD`.
- **Dependency caching**: ligado pelo `cache:` do YAML (bootstrap + Gradle), o build repetido cai
  de ~10 min para ~3 min.

### Disparar pela API (opcional)

```sh
curl -s -X POST https://api.codemagic.io/builds \
  -H "x-auth-token: $CODEMAGIC_TOKEN" -H "Content-Type: application/json" \
  -d '{"appId":"6af11769a4abdfa900b420cb","workflowId":"android-apk",
       "branch":"arena/65202ee3-rea-termuxreboot"}'
```

### Antigo caminho de 5 minutos (para referência)

O APK sai em **Artifacts** com link público (30 dias).

## 4. Azure Pipelines

dev.azure.com → *New project* → *Pipelines → New pipeline* → GitHub →
`Legitms9/Rea-termuxReboot` → *Existing Azure Pipelines YAML file* → `/azure-pipelines.yml` →
Run. O APK aparece em *Artifacts* (`rea-ide-apk`). Grátis para repo público, sem cartão.

## 5. Codespaces / Gitpod

**Codespaces**: github.com/codespaces → *New codespace* neste repo → no terminal:

```sh
bash scripts/build_cloudshell.sh
```

Depois, no explorador de arquivos do VS Code web: botão direito em
`~/rea-apk/*.apk` → *Download*.

**Gitpod**: `https://gitpod.io/#https://github.com/Legitms9/Rea-termuxReboot` e o mesmo comando.

## 6. Docker em qualquer máquina com internet

```sh
docker build -f docker/Dockerfile -t rea-ide-build .
mkdir -p out
docker run --rm -v "$PWD/out:/out" -v "$PWD:/src" -w /src \
  -e GH_TOKEN="$(gh auth token)" rea-ide-build
ls out/*.apk
```

Não precisa de Android SDK nem JDK na máquina — só Docker. Funciona em qualquer VPS, no WSL, num
servidor de amigo. Se não tiver `gh`, o script cai para download HTTP puro
(`REA_BOOTSTRAP_PROXY` opcional).

---

## Antes de culpar o build: o que já está verde

O que dá para verificar sem compilar nada:

```sh
python3 scripts/patch_bootstrap.py --check      # invariante do applicationId
python3 scripts/test_prepare_bootstrap.py       # 30 asserções do patcher
cd web && npm ci && npm run build && npm test   # editor em DOM real + filtro ANSI
```

## Problemas prováveis no primeiro build real

| Sintoma | Causa | Correção |
|---|---|---|
| `Bootstrap ausente para [...]` | rodou `gradlew` sem o passo do bootstrap | rode `scripts/prepare_bootstrap.py` antes (ou use o `build_cloudshell.sh`) |
| `Could not find com.android.tools.build:gradle` | sem internet para `google()`/`mavenCentral()` | libere `dl.google.com`, `repo1.maven.org` |
| `NDK not configured` | SDK sem NDK 26.1 | `sdkmanager "ndk;26.1.10909125"` |
| `Asset 'www/index.html' não encontrado` → tela branca | build sem o passo web | `-Prea.webPrefetched=true` só se `web/dist` existir |
| APK instala e fecha ao abrir | bootstrap corrompido/ABI errada | confira a ABI do aparelho (`adb shell getprop ro.product.cpu.abi`) |
| `gh: command not found` | CI sem GitHub CLI | já tem fallback HTTP; ou `REA_BOOTSTRAP_PROXY=https://ghproxy.net/https://github.com` |

Manda o log da primeira falha que eu ajusto — as linhas de cima cobrem os casos que já vi.
