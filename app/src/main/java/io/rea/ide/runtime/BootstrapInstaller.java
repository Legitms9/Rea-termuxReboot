package io.rea.ide.runtime;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Installs the Termux bootstrap that ships inside the APK.
 *
 * <p>The archive lives at {@code lib/<abi>/libtermux-bootstrap.so}, which lets Android's normal
 * packaging deliver one archive per ABI. With {@code android:extractNativeLibs="true"} it is a plain,
 * seekable file at {@code ApplicationInfo.nativeLibraryDir}, readable by us with no permissions
 * games (unlike assets, it is not compressed inside the APK).
 *
 * <p>Pipeline:
 * <ol>
 *   <li>clear {@code $FILES/usr-staging} and {@code $FILES/usr};
 *   <li>stream-unzip the archive into the staging dir, recording modes;
 *   <li>apply {@code REA-INSTALL-MANIFEST.json} (chmod +x on the ~1200 executables);
 *   <li>recreate symlinks from {@code SYMLINKS.txt} (upstream format, {@code target←link});
 *   <li>atomically rename staging -> {@code $FILES/usr};
 *   <li>drop marker {@code $PREFIX/.rea-bootstrap-ok}.
 * </ol>
 */
public final class BootstrapInstaller {

    private static final String TAG = "BootstrapInstaller";
    private static final String ARCHIVE_NAME = "libtermux-bootstrap.so";
    private static final String MANIFEST_NAME = "REA-INSTALL-MANIFEST.json";
    private static final String SYMLINKS_NAME = "SYMLINKS.txt";
    public static final String OK_MARKER = ".rea-bootstrap-ok";

    public interface Progress {
        void onProgress(String message, int extracted, int total);
    }

    private final Context context;

    public BootstrapInstaller(Context context) {
        this.context = context.getApplicationContext();
    }

    public File archiveFile() {
        File libDir = new File(context.getApplicationInfo().nativeLibraryDir);
        return new File(libDir, ARCHIVE_NAME);
    }

    public boolean isInstalled() {
        return ReaPaths.isBootstrapped();
    }

    /** Blocking. Call from a worker thread. */
    public void install(Progress progress) throws IOException {
        File archive = archiveFile();
        if (!archive.exists()) {
            throw new IOException("Bootstrap archive missing at " + archive
                    + " (nativeLibraryDir=" + context.getApplicationInfo().nativeLibraryDir + ")");
        }

        File staging = new File(ReaPaths.stagingPrefix());
        File target = new File(ReaPaths.prefix());

        report(progress, "Preparando diretórios…", 0, 1);
        deleteRecursively(staging);
        deleteRecursively(target);
        mkdirOrThrow(staging);
        mkdirOrThrow(new File(ReaPaths.home()));

        List<String> symlinks = new ArrayList<>();
        JSONArray executables = null;
        int extracted = 0;

        try (ZipInputStream zin = new ZipInputStream(
                new BufferedInputStream(new java.io.FileInputStream(archive), 1 << 16))) {
            ZipEntry entry;
            byte[] buf = new byte[1 << 16];
            while ((entry = zin.getNextEntry()) != null) {
                String name = entry.getName();

                if (name.equals(SYMLINKS_NAME)) {
                    readSymlinks(zin, symlinks);
                    continue;
                }
                if (name.equals(MANIFEST_NAME)) {
                    executables = readManifestExecutables(zin);
                    continue;
                }

                File out = new File(staging, name);
                if (entry.isDirectory()) {
                    mkdirOrThrow(out);
                    continue;
                }
                File parent = out.getParentFile();
                if (parent != null) mkdirOrThrow(parent);

                try (FileOutputStream fos = new FileOutputStream(out)) {
                    int n;
                    while ((n = zin.read(buf)) > 0) fos.write(buf, 0, n);
                }
                extracted++;
                if ((extracted & 0xFF) == 0) {
                    report(progress, "Extraindo " + extracted + " arquivos…", extracted, -1);
                }
            }
        }

        report(progress, "Aplicando permissões…", extracted, extracted);
        if (executables != null) {
            for (int i = 0; i < executables.length(); i++) {
                File f = new File(staging, executables.optString(i));
                chmod(f, 0700);
            }
        } else {
            // Manifest missing: fall back to the upstream heuristic.
            chmodTree(staging);
        }

        report(progress, "Criando links simbólicos…", extracted, extracted);
        for (String line : symlinks) {
            int sep = line.indexOf('←');
            if (sep <= 0) continue;
            String targetPath = line.substring(0, sep);
            String linkPath = line.substring(sep + 1);
            File link = new File(staging, linkPath);
            File linkParent = link.getParentFile();
            if (linkParent != null) mkdirOrThrow(linkParent);
            if (link.exists() || isSymlink(link)) {
                //noinspection ResultOfMethodCallIgnored
                link.delete();
            }
            try {
                Os.symlink(targetPath, link.getAbsolutePath());
            } catch (ErrnoException e) {
                Log.w(TAG, "symlink failed: " + linkPath + " -> " + targetPath, e);
            }
        }

        report(progress, "Finalizando…", extracted, extracted);
        File tmp = new File(ReaPaths.tmpPrefix());
        mkdirOrThrow(tmp);
        mkdirOrThrow(new File(ReaPaths.varPrefix() + "/run"));

        if (!staging.renameTo(target)) {
            throw new IOException("Could not move " + staging + " to " + target);
        }

        writeMarker(target);
        installHelperScripts(target);

        report(progress, "Pronto.", extracted, extracted);
        Log.i(TAG, "Bootstrap installed: " + extracted + " files, " + symlinks.size() + " symlinks");
    }

    // ------------------------------------------------------------------ helpers

    private void installHelperScripts(File prefix) {
        // These are generated here (not shipped as assets) so the paths always match ReaPaths.
        File etcRea = new File(prefix, "etc/rea");
        try {
            mkdirOrThrow(etcRea);
        } catch (IOException e) {
            Log.w(TAG, "could not create helper directory " + etcRea, e);
            return;
        }
        writeScript(new File(etcRea, "rea-open"),
                "#!/data/data/" + ReaPaths.packageName() + "/files/usr/bin/sh\n"
                        + "# Open a path in the REA IDE (called by file managers / other apps).\n"
                        + "echo \"$1\" > \"$PREFIX/tmp/.rea-open-request\"\n");
        writeScript(new File(etcRea, "rea-run"),
                "#!/data/data/" + ReaPaths.packageName() + "/files/usr/bin/sh\n"
                        + "# Run a project's entrypoint with the workspace on PATH.\n"
                        + "cd \"${1:-$HOME}\" && exec \"${2:-bash}\"\n");
    }

    private void writeScript(File f, String body) {
        try {
            try (FileOutputStream fos = new FileOutputStream(f)) {
                fos.write(body.getBytes("UTF-8"));
            }
            chmod(f, 0700);
        } catch (IOException e) {
            Log.w(TAG, "could not write helper " + f, e);
        }
    }

    private void writeMarker(File prefix) {
        File marker = new File(prefix, OK_MARKER);
        try (FileOutputStream fos = new FileOutputStream(marker)) {
            JSONObject o = new JSONObject();
            o.put("abi", android.os.Build.SUPPORTED_ABIS[0]);
            o.put("installedAt", System.currentTimeMillis());
            o.put("package", ReaPaths.packageName());
            fos.write(o.toString().getBytes("UTF-8"));
        } catch (Exception e) {
            Log.w(TAG, "could not write bootstrap marker", e);
        }
    }

    private static void readSymlinks(InputStream in, List<String> out) throws IOException {
        BufferedReader reader = new BufferedReader(new InputStreamReader(in, "UTF-8"));
        String line;
        while ((line = reader.readLine()) != null) {
            if (!line.isEmpty()) out.add(line);
        }
    }

    private static JSONArray readManifestExecutables(InputStream in) {
        try {
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            JSONObject root = new JSONObject(new String(bos.toByteArray(), "UTF-8"));
            return root.optJSONArray("executables");
        } catch (Exception e) {
            Log.w(TAG, "manifest unreadable, falling back to path heuristics", e);
            return null;
        }
    }

    private static void chmod(File f, int mode) {
        try {
            Os.chmod(f.getAbsolutePath(), mode);
        } catch (Exception e) {
            Log.w(TAG, "chmod failed: " + f, e);
        }
    }

    private static void chmodTree(File root) {
        File[] children = root.listFiles();
        if (children == null) return;
        for (File child : children) {
            if (child.isDirectory()) {
                chmodTree(child);
            } else if (!isSymlink(child)) {
                String rel = child.getAbsolutePath().substring(root.getAbsolutePath().length() + 1);
                if (rel.startsWith("bin/") || rel.startsWith("libexec/")
                        || rel.startsWith("lib/apt/methods/") || rel.startsWith("lib/apt/apt-helper")
                        || rel.equals("etc/termux/bootstrap/termux-bootstrap-second-stage.sh")) {
                    chmod(child, 0700);
                }
            }
        }
    }

    /**
     * True only for a symlink (including a dangling one). {@code File.isFile()/exists()} follow
     * links and would lie about dangling entries, which the bootstrap is full of.
     */
    private static boolean isSymlink(File f) {
        try {
            android.system.StructStat st = android.system.Os.lstat(f.getAbsolutePath());
            return (st.st_mode & android.system.OsConstants.S_IFMT)
                    == android.system.OsConstants.S_IFLNK;
        } catch (Exception e) {
            return false;
        }
    }

    private static void mkdirOrThrow(File dir) throws IOException {
        if (dir.isDirectory()) return;
        if (!dir.mkdirs() && !dir.isDirectory()) {
            throw new IOException("Cannot create directory " + dir);
        }
    }

    private static void report(Progress p, String msg, int done, int total) {
        if (p != null) p.onProgress(msg, done, total);
    }

    public static void deleteRecursively(File f) {
        if (f == null) return;
        if (!f.exists() && !isSymlink(f)) return;
        File[] children = f.listFiles();
        if (children != null) {
            for (File c : children) deleteRecursively(c);
        }
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }
}
