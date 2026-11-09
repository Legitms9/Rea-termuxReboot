package io.rea.ide.runtime;

import java.io.File;

/**
 * Where everything lives on the device.
 *
 * <p>We deliberately use the legacy {@code /data/data/<pkg>} spelling instead of the value of
 * {@code Context.getFilesDir()}: on multi-user devices the framework hands back
 * {@code /data/user/0/<pkg>/files}, which is a different string (and a different length) than the
 * one baked into the Termux binaries. Everything that touches the prefix must agree on one
 * spelling, so this class is the single source of truth.
 *
 * <pre>
 * /data/data/io.rea.ide/
 *   files/                 FILES   (we call it $ROOTFS)
 *     usr/                 PREFIX  (bin, lib, etc, share, tmp, var)
 *     usr-staging/         bootstrap extraction area
 *     home/                HOME    (workspace root)
 *       projects/
 *         hello-web/       default project opened on first launch
 * </pre>
 */
public final class ReaPaths {

    private ReaPaths() {}

    /** Hard-coded, because the binaries hard-code it too. Must stay 10 chars for the app id. */
    public static final String LEGACY_DATA_ROOT = "/data/data";

    private static String packageName = "io.rea.ide";

    public static void init(String pkg) {
        packageName = pkg;
    }

    public static String packageName() {
        return packageName;
    }

    public static String filesDir() {
        return LEGACY_DATA_ROOT + "/" + packageName + "/files";
    }

    public static String prefix() {
        return filesDir() + "/usr";
    }

    public static String stagingPrefix() {
        return filesDir() + "/usr-staging";
    }

    public static String home() {
        return filesDir() + "/home";
    }

    public static String projects() {
        return home() + "/projects";
    }

    public static String binPrefix() {
        return prefix() + "/bin";
    }

    public static String tmpPrefix() {
        return prefix() + "/tmp";
    }

    public static String etcPrefix() {
        return prefix() + "/etc";
    }

    public static String varPrefix() {
        return prefix() + "/var";
    }

    public static File file(String path) {
        return new File(path);
    }

    public static boolean isBootstrapped() {
        // A prefix with bin/bash is what the upstream installer considers "done".
        return new File(binPrefix(), "bash").exists()
                && new File(prefix(), ".rea-bootstrap-ok").exists();
    }
}
