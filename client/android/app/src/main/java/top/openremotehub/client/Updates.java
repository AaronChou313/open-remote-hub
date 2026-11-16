package top.openremotehub.client;

import android.os.Handler;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.function.Consumer;
import org.json.*;

/** Checks the public release feed for a newer ORH client. */
final class Updates {
    private static final String FEED = "https://api.github.com/repos/AaronChou313/open-remote-hub/releases/latest";

    static final class Release {
        final String version, notes, url;
        Release(String version, String notes, String url) {
            this.version = version; this.notes = notes; this.url = url;
        }
    }

    private Updates() {}

    static void check(ExecutorService worker, Handler main, String current, Consumer<Release> done, Consumer<String> failure) {
        worker.execute(() -> {
            Release found = null;
            try {
                HttpURLConnection connection = (HttpURLConnection) new URL(FEED).openConnection();
                connection.setConnectTimeout(6000);
                connection.setReadTimeout(8000);
                connection.setRequestProperty("Accept", "application/vnd.github+json");
                connection.setRequestProperty("User-Agent", "ORH-Client/" + current);
                if (connection.getResponseCode() == 200) {
                    JSONObject value = new JSONObject(read(connection.getInputStream()));
                    String tag = value.optString("tag_name", "").replaceFirst("^[vV]", "");
                    String url = "";
                    JSONArray assets = value.optJSONArray("assets");
                    for (int index = 0; assets != null && index < assets.length(); index++) {
                        JSONObject asset = assets.optJSONObject(index);
                        if (asset != null && asset.optString("name").endsWith(".apk")) {
                            url = asset.optString("browser_download_url");
                            break;
                        }
                    }
                    if (url.isEmpty()) url = value.optString("html_url");
                    if (!tag.isEmpty() && newer(tag, current)) found = new Release(tag, value.optString("body", ""), url);
                }
                else throw new IOException("HTTP "+connection.getResponseCode());
                connection.disconnect();
            } catch (Exception error) {main.post(() -> failure.accept("检查更新失败，请稍后重试。"));return;}
            Release result = found;
            main.post(() -> done.accept(result));
        });
    }

    static boolean newer(String candidate, String current) {
        int[] left = parts(candidate), right = parts(current);
        for (int index = 0; index < Math.max(left.length, right.length); index++) {
            int a = index < left.length ? left[index] : 0;
            int b = index < right.length ? right[index] : 0;
            if (a != b) return a > b;
        }
        return false;
    }

    private static int[] parts(String value) {
        List<Integer> numbers = new ArrayList<>();
        for (String piece : value.split("[^0-9]+")) {
            if (!piece.isEmpty() && piece.length() < 9) numbers.add(Integer.parseInt(piece));
        }
        int[] result = new int[numbers.size()];
        for (int index = 0; index < result.length; index++) result[index] = numbers.get(index);
        return result;
    }

    private static String read(InputStream stream) throws IOException {
        StringBuilder text = new StringBuilder();
        try (BufferedReader input = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = input.readLine()) != null) text.append(line).append('\n');
        }
        return text.toString();
    }
}
