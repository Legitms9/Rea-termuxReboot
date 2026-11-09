# Build em container

```sh
docker build -f docker/Dockerfile -t rea-ide-build .

mkdir -p out
docker run --rm \
  -v "$PWD/out:/out" \
  -v "$PWD:/src" \
  -w /src \
  -e GH_TOKEN="$(gh auth token)" \
  -e ABIS=arm64-v8a \
  rea-ide-build
```

Saída: `out/rea-termux-ide-<versão>-debug-<abi>.apk` + `SHA256SUMS.txt`.

Notas:

- a imagem tem JDK 17, SDK 34, NDK 26.1 e `gh`; ~4 GB;
- o bootstrap (~40 MB por ABI) é baixado em tempo de build e verificado por SHA-256;
- `-e ABIS=arm64-v8a,armeabi-v7a` gera múltiplas ABIs no mesmo APK universal
  (o APK fica grande: ~35 MB por ABI);
- para release assinado, exporte `REA_KEYSTORE_FILE`, `REA_KEYSTORE_PASSWORD`,
  `REA_KEY_ALIAS`, `REA_KEY_PASSWORD` e use `assembleRelease` no entrypoint.
