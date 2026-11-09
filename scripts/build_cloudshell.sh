#!/usr/bin/env bash
#
# build_cloudshell.sh — compila o APK numa máquina Linux *temporária e gratuita*,
# sem GitHub Actions, sem Docker e sem instalar nada no seu celular/PC.
#
# Onde rodar (qualquer VM Linux com ~10 GB livres e internet):
#   • Google Cloud Shell  → shell.cloud.google.com        (grátis, 5 GB, ~30 min de sessão)
#   • GitHub Codespaces   → github.com/codespaces         (60 h/mês grátis)
#   • Gitpod              → gitpod.io                     (50 h/mês grátis)
#   • um Termux em outro celular, uma VPS, um Raspberry Pi…
#
# Uso:
#   curl -fsSL https://raw.githubusercontent.com/Legitms9/Rea-termuxReboot/arena/65202ee3-rea-termuxreboot/scripts/build_cloudshell.sh | bash
#
#   # ou, já dentro do repo:
#   bash scripts/build_cloudshell.sh                      # arm64-v8a (padrão)
#   ABIS=arm64-v8a,armeabi-v7a bash scripts/build_cloudshell.sh
#
# No fim ele imprime o caminho do APK e o tamanho. Baixe pelo botão "Download" do
# Cloud Shell (⋮ → Download file) ou sirva com `python3 -m http.server` e abra a URL.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Legitms9/Rea-termuxReboot.git}"
REPO_REF="${REPO_REF:-arena/65202ee3-rea-termuxreboot}"
APP_ID="${REA_APP_ID:-io.rea.ide}"
BOOTSTRAP_RELEASE="${BOOTSTRAP_RELEASE:-bootstrap-2026.11.08-r1+apt.android-7}"
ABIS="${ABIS:-arm64-v8a}"
SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
NDK_VERSION="26.1.10909125"

step() { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
have() { command -v "$1" > /dev/null 2>&1; }

# ---------------------------------------------------------------- 1. repositório
step "1/6 repositório"
if [ -f "./gradlew" ] && [ -d "./scripts" ]; then
  SRC="$PWD"
  echo "usando o checkout atual: $SRC"
else
  SRC="$HOME/rea-ide-build/Rea-termuxReboot"
  rm -rf "$SRC"
  mkdir -p "$(dirname "$SRC")"
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$SRC"
fi
cd "$SRC"

# ---------------------------------------------------------------- 2. dependências
step "2/6 dependências do sistema"
if ! have java; then
  if have apt-get; then
    (sudo apt-get update -qq && sudo apt-get install -y -qq openjdk-17-jdk-headless unzip curl python3 git) \
      || sudo apt-get install -y openjdk-17-jdk-headless unzip curl python3 git
  else
    echo "Instale JDK 17, unzip e curl manualmente e rode de novo." >&2
    exit 1
  fi
fi
java -version 2>&1 | head -2

if ! have node; then
  echo "Node não encontrado; instalando via nvm"
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
  # shellcheck disable=SC1091
  . "$HOME/.nvm/nvm.sh" && nvm install 20
fi
node --version

# ---------------------------------------------------------------- 3. Android SDK
step "3/6 Android SDK + NDK"
if [ ! -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]; then
  mkdir -p "$SDK_ROOT/cmdline-tools"
  curl -fsSL -o /tmp/cmdline-tools.zip \
    https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q /tmp/cmdline-tools.zip -d "$SDK_ROOT/cmdline-tools"
  mv "$SDK_ROOT/cmdline-tools/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"
  rm -f /tmp/cmdline-tools.zip
fi
export ANDROID_SDK_ROOT="$SDK_ROOT" ANDROID_HOME="$SDK_ROOT"
export PATH="$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools:$PATH"
yes | sdkmanager --licenses > /dev/null 2>&1 || true
sdkmanager --install "platforms;android-34" "build-tools;34.0.0" "ndk;$NDK_VERSION" "platform-tools" > /dev/null

# ---------------------------------------------------------------- 4. web + testes
step "4/6 editor web + testes"
( cd web && npm ci --no-audit --no-fund && npm run build && npm test )

step "testes do patcher do bootstrap"
python3 scripts/patch_bootstrap.py --check --app-id "$APP_ID"
python3 scripts/test_prepare_bootstrap.py

# ---------------------------------------------------------------- 5. bootstrap
step "5/6 bootstrap do Termux ($ABIS)"
# ~40 MB por ABI, baixado e verificado por sha256; fica em jniLibs e entra no APK.
python3 scripts/prepare_bootstrap.py \
  --release "$BOOTSTRAP_RELEASE" \
  --app-id "$APP_ID" \
  --abis "$ABIS" \
  --out-dir app/src/main/jniLibs \
  --cache-dir build/bootstrap-cache

# ---------------------------------------------------------------- 6. APK
step "6/6 compilando o APK"
./gradlew --no-daemon assembleDebug \
  -Prea.abis="$ABIS" \
  -Prea.bootstrapRelease="$BOOTSTRAP_RELEASE" \
  -Prea.webPrefetched=true

APK_DIR="app/build/outputs/apk/debug"
APK=$(find "$APK_DIR" -name '*.apk' | head -1)
if [ -z "$APK" ]; then
  echo "Nenhum APK encontrado em $APK_DIR" >&2
  exit 1
fi

SIZE=$(du -h "$APK" | cut -f1)
SHA=$(sha256sum "$APK" | cut -d' ' -f1)

# deixa o artefato num lugar fácil de baixar
mkdir -p "$HOME/rea-apk"
cp "$APK" "$HOME/rea-apk/"
BASENAME=$(basename "$APK")

cat <<EOF

\033[1;32mAPK pronto\033[0m
  arquivo : $HOME/rea-apk/$BASENAME
  tamanho : $SIZE
  sha256  : $SHA

Baixar:
  • Cloud Shell: ⋮ (menu) → Download → informe o caminho acima
  • Codespaces: clique com o botão direito no arquivo → Download…
  • ou sirva localmente:
      cd "$HOME/rea-apk" && python3 -m http.server 8000
    (Cloud Shell: "Web preview" → porta 8000)

Instalar no celular:
  adb install -r "$BASENAME"
  # ou copie o .apk para o celular e abra (permita "fontes desconhecidas")

Na primeira execução o app extrai o bootstrap (~40 MB) para
  /data/data/$APP_ID/files/usr
e leva alguns segundos.
EOF
