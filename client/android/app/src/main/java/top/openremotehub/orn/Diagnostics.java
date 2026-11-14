package top.openremotehub.orn;

import android.content.Context;
import java.io.*;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** App-private, bounded connection log. No credentials or peer contents are written. */
final class Diagnostics {
    private static final long LIMIT = 128 * 1024;
    private static final int KEEP = 2;
    private static Context context;

    private Diagnostics() {}

    static synchronized void attach(Context value) {
        if (context == null && value != null) context = value.getApplicationContext();
    }

    static synchronized File file() {
        if (context == null) return null;
        return new File(context.getFilesDir(), "diagnostics.log");
    }

    static synchronized void log(String tag, String message) {
        File target = file();
        if (target == null) return;
        String line = new SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US).format(new Date()) + " [" + tag + "] " + message + "\n";
        try {
            if (target.length() + line.length() > LIMIT) rotate(target);
            try (Writer output = new OutputStreamWriter(new FileOutputStream(target, true), "UTF-8")) {
                output.write(line);
            }
        } catch (IOException ignored) {}
    }

    private static void rotate(File target) {
        File root = target.getParentFile();
        new File(root, "diagnostics." + KEEP + ".log").delete();
        for (int index = KEEP - 1; index >= 1; index--) {
            new File(root, "diagnostics." + index + ".log")
                .renameTo(new File(root, "diagnostics." + (index + 1) + ".log"));
        }
        target.renameTo(new File(root, "diagnostics.1.log"));
    }

    /** Tail of the log for the on-device dialog, capped to keep the clipboard usable. */
    static synchronized String tail(int limit) {
        File target = file();
        if (target == null || !target.isFile()) return "";
        try (RandomAccessFile input = new RandomAccessFile(target, "r")) {
            long start = Math.max(0, input.length() - limit);
            input.seek(start);
            byte[] data = new byte[(int) (input.length() - start)];
            input.readFully(data);
            return new String(data, "UTF-8");
        } catch (IOException error) {
            return "无法读取日志: " + error.getMessage();
        }
    }
}
