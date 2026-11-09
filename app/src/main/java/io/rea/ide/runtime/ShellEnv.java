package io.rea.ide.runtime;

import android.content.pm.ApplicationInfo;
import android.os.Build;

import java.util.ArrayList;
import java.util.List;

/**
 * Builds the environment a Termux process expects.
 *
 * <p>Derived from termux-app's {@code TermuxShellUtils.buildEnvironment()} (GPLv3), trimmed to what
 * an IDE needs and re-pointed at {@link ReaPaths} so the exact same prefixes that were patched into
 * the bootstrap are used at runtime.
 */
public final class ShellEnv {

    private ShellEnv() {}

    public static String[] build(String workingDir, boolean failSafe) {
        if (workingDir == null || workingDir.isEmpty()) workingDir = ReaPaths.home();
        List<String> env = new ArrayList<>();

        env.add("TERM=xterm-256color");
        env.add("COLORTERM=truecolor");
        env.add("TERMUX_VERSION=rea-ide");
        env.add("REA_IDE=1");

        env.add("HOME=" + ReaPaths.home());
        env.add("TERMUX__HOME=" + ReaPaths.home());
        env.add("PREFIX=" + ReaPaths.prefix());
        env.add("TERMUX__PREFIX=" + ReaPaths.prefix());
        env.add("TERMUX__ROOTFS_DIR=" + ReaPaths.filesDir());
        env.add("TERMUX_APP__DATA_DIR=" + ReaPaths.filesDir().replace("/files", ""));

        // Android internals some tools (am, pm, dalvik) insist on.
        env.add("ANDROID_ROOT=" + orEmpty(System.getenv("ANDROID_ROOT")));
        env.add("ANDROID_DATA=" + orEmpty(System.getenv("ANDROID_DATA")));
        env.add("BOOTCLASSPATH=" + orEmpty(System.getenv("BOOTCLASSPATH")));
        env.add("EXTERNAL_STORAGE=" + orEmpty(System.getenv("EXTERNAL_STORAGE")));
        addIfPresent(env, "ANDROID_ART_ROOT");
        addIfPresent(env, "DEX2OATBOOTCLASSPATH");
        addIfPresent(env, "ANDROID_I18N_ROOT");
        addIfPresent(env, "ANDROID_RUNTIME_ROOT");
        addIfPresent(env, "ANDROID_TZDATA_ROOT");
        env.add("ANDROID__BUILD_VERSION_SDK=" + Build.VERSION.SDK_INT);

        if (failSafe) {
            env.add("PATH= " + orEmpty(System.getenv("PATH")));
        } else {
            env.add("LANG=en_US.UTF-8");
            env.add("LC_ALL=en_US.UTF-8");
            env.add("PATH=" + ReaPaths.binPrefix());
            env.add("PWD=" + workingDir);
            env.add("TMPDIR=" + ReaPaths.tmpPrefix());
            // The IDE's own helper scripts (rea-open, rea-run) are first in PATH.
            env.add("REA_IDE_BIN=" + ReaPaths.prefix() + "/etc/rea");
        }
        return env.toArray(new String[0]);
    }

    private static void addIfPresent(List<String> env, String name) {
        String v = System.getenv(name);
        if (v != null) env.add(name + "=" + v);
    }

    private static String orEmpty(String s) {
        return s == null ? "" : s;
    }

    /** Shortens a path for display: /data/data/io.rea.ide/files/home/proj -> ~/proj */
    public static String prettyPath(String path) {
        if (path == null) return "";
        if (path.equals(ReaPaths.home())) return "~";
        if (path.startsWith(ReaPaths.home())) return "~" + path.substring(ReaPaths.home().length());
        if (path.startsWith(ReaPaths.prefix())) return "$PREFIX" + path.substring(ReaPaths.prefix().length());
        return path;
    }
}
