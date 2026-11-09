package io.rea.ide;

import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

import io.rea.ide.runtime.ReaPaths;

/**
 * Thin, dependency-free file layer for the editor. All paths are absolute; the UI only ever sees
 * paths under {@code $HOME}.
 */
public final class Workspace {

    private static final String TAG = "Workspace";
    public static final long MAX_EDITABLE_BYTES = 4L * 1024 * 1024;

    public static final class Entry {
        public final String name;
        public final String path;
        public final boolean directory;
        public final long size;

        Entry(File f) {
            this.name = f.getName();
            this.path = f.getAbsolutePath();
            this.directory = f.isDirectory();
            this.size = f.isDirectory() ? 0 : f.length();
        }

        public String subtitle() {
            if (directory) return "pasta";
            // Entry é uma classe aninhada estática: não herda os métodos de Workspace,
            // precisa do nome da classe externa para chamar o helper.
            return Workspace.humanSize(size);
        }
    }

    public static final class FileText {
        public final String path;
        public final String text;
        public final boolean binary;

        FileText(String path, String text, boolean binary) {
            this.path = path;
            this.text = text;
            this.binary = binary;
        }
    }

    private Workspace() {}

    public static File home() {
        File f = new File(ReaPaths.home());
        if (!f.exists() && !f.mkdirs()) Log.w(TAG, "could not create " + f);
        return f;
    }

    public static File projects() {
        File f = new File(ReaPaths.projects());
        if (!f.exists() && !f.mkdirs()) Log.w(TAG, "could not create " + f);
        return f;
    }

    /** Lists a directory: directories first, then files, both alphabetical. Hidden files last. */
    public static List<Entry> list(String dir) {
        File d = new File(dir);
        File[] children = d.listFiles();
        List<Entry> out = new ArrayList<>();
        if (children == null) return out;
        Arrays.sort(children, new Comparator<File>() {
            @Override public int compare(File a, File b) {
                boolean ah = a.getName().startsWith("."), bh = b.getName().startsWith(".");
                if (ah != bh) return ah ? 1 : -1;
                if (a.isDirectory() != b.isDirectory()) return a.isDirectory() ? -1 : 1;
                return a.getName().compareToIgnoreCase(b.getName());
            }
        });
        for (File c : children) out.add(new Entry(c));
        return out;
    }

    public static boolean isText(String path) {
        String lower = path.toLowerCase(Locale.US);
        String[] binaryExt = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".so", ".a", ".o", ".class",
                ".jar", ".zip", ".gz", ".xz", ".apk", ".dex", ".ttf", ".mp3", ".mp4", ".db", ".sqlite"};
        for (String e : binaryExt) if (lower.endsWith(e)) return false;
        return true;
    }

    public static FileText read(String path) throws IOException {
        File f = new File(path);
        if (!f.exists()) throw new IOException("Arquivo não encontrado: " + path);
        if (f.length() > MAX_EDITABLE_BYTES) {
            throw new IOException("Arquivo grande demais para o editor (" + humanSize(f.length()) + ")");
        }
        byte[] bytes = new byte[(int) f.length()];
        try (FileInputStream in = new FileInputStream(f)) {
            int off = 0;
            while (off < bytes.length) {
                int n = in.read(bytes, off, bytes.length - off);
                if (n < 0) break;
                off += n;
            }
        }
        // NUL byte in the first 8 KiB => treat as binary, do not pretend to edit it.
        int probe = Math.min(bytes.length, 8192);
        for (int i = 0; i < probe; i++) if (bytes[i] == 0) {
            return new FileText(path, "", true);
        }
        return new FileText(path, new String(bytes, StandardCharsets.UTF_8), false);
    }

    public static void write(String path, String text) throws IOException {
        File f = new File(path);
        File parent = f.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("Não foi possível criar " + parent);
        }
        // Write atomically: temp file + rename, so a crash never truncates a source file.
        File tmp = new File(f.getParentFile(), "." + f.getName() + ".rea-tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        }
        if (f.exists() && !f.delete()) Log.w(TAG, "could not delete old " + f);
        if (!tmp.renameTo(f)) throw new IOException("Falha ao gravar " + path);
    }

    public static boolean createFile(String path) {
        try {
            File f = new File(path);
            File parent = f.getParentFile();
            if (parent != null) parent.mkdirs();
            return f.createNewFile();
        } catch (IOException e) {
            Log.w(TAG, "createFile", e);
            return false;
        }
    }

    public static boolean createDir(String path) {
        return new File(path).mkdirs();
    }

    public static boolean delete(String path) {
        File f = new File(path);
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) delete(k.getAbsolutePath());
        return f.delete();
    }

    public static boolean rename(String from, String to) {
        File target = new File(to);
        File parent = target.getParentFile();
        if (parent != null) parent.mkdirs();
        return new File(from).renameTo(target);
    }

    public static String humanSize(long bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return String.format(Locale.US, "%.1f KB", bytes / 1024.0);
        if (bytes < 1024L * 1024 * 1024) return String.format(Locale.US, "%.1f MB", bytes / (1024.0 * 1024));
        return String.format(Locale.US, "%.1f GB", bytes / (1024.0 * 1024 * 1024));
    }

    /** Breadcrumb segments for $HOME-relative paths, e.g. ~ / projects / app. */
    public static List<String> breadcrumb(String path) {
        List<String> out = new ArrayList<>();
        String home = ReaPaths.home();
        String rel = path.startsWith(home) ? "~" + path.substring(home.length()) : path;
        for (String part : rel.split("/")) if (!part.isEmpty()) out.add(part);
        return out;
    }

    public static String readAll(java.io.InputStream in) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        return new String(bos.toByteArray(), StandardCharsets.UTF_8);
    }
}
