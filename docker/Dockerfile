# Reproducible APK build without a local Android SDK.
#
#   docker build -f docker/Dockerfile -t rea-ide-build .
#   docker run --rm -v "$PWD/out:/out" -v "$PWD:/src" -w /src \
#     -e GH_TOKEN="$(gh auth token)" rea-ide-build
#
# Produces /out/rea-termux-ide-*.apk. The bootstrap is downloaded at build time (it is not in
# the repo), which needs network access to github.com.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk \
    NDK_VERSION=26.1.10909125 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jdk-headless unzip zip python3 python3-pip curl ca-certificates git \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Android command line tools
ARG CMDLINE_TOOLS=commandlinetools-linux-11076708_latest.zip
RUN mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools" \
    && curl -fsSL -o /tmp/tools.zip "https://dl.google.com/android/repository/${CMDLINE_TOOLS}" \
    && unzip -q /tmp/tools.zip -d "$ANDROID_SDK_ROOT/cmdline-tools" \
    && mv "$ANDROID_SDK_ROOT/cmdline-tools/cmdline-tools" "$ANDROID_SDK_ROOT/cmdline-tools/latest" \
    && rm /tmp/tools.zip \
    && yes | "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" --licenses > /dev/null \
    && "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" \
         "platform-tools" "platforms;android-34" "build-tools;34.0.0" "ndk;${NDK_VERSION}"

ENV PATH="$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$PATH"

# GitHub CLI (used to fetch the Termux bootstrap release assets)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

COPY docker/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

ENTRYPOINT ["/usr/local/bin/entrypoint"]
