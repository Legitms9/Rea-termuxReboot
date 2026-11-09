#!/usr/bin/env bash
# Builds the APK inside the container and copies it to /out.
set -euo pipefail

ABIS="${ABIS:-arm64-v8a}"
BOOTSTRAP_RELEASE="${BOOTSTRAP_RELEASE:-bootstrap-2026.11.08-r1+apt.android-7}"
APP_ID="io.rea.ide"

echo "== invariante do applicationId"
python3 scripts/patch_bootstrap.py --check --app-id "$APP_ID"

echo "== testes do patcher"
python3 scripts/test_prepare_bootstrap.py

echo "== editor web"
( cd web && npm ci --no-audit --no-fund && npm run build && npm test )

echo "== bootstrap ($ABIS)"
python3 scripts/prepare_bootstrap.py \
  --release "$BOOTSTRAP_RELEASE" \
  --app-id "$APP_ID" \
  --abis "$ABIS" \
  --out-dir app/src/main/jniLibs \
  --cache-dir build/bootstrap-cache

echo "== APK"
./gradlew --no-daemon assembleDebug \
  -Prea.abis="$ABIS" \
  -Prea.bootstrapRelease="$BOOTSTRAP_RELEASE" \
  -Prea.webPrefetched=true

mkdir -p /out
find app/build/outputs/apk -name '*.apk' -exec cp {} /out/ \;
( cd /out && sha256sum *.apk | tee SHA256SUMS.txt )
echo "== pronto: /out"
