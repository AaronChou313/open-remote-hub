package top.openremotehub.orn;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import org.json.*;
import top.openremotehub.orn.core.mobile.Mobile;

/** Loopback client for the Go core's LocalAPI, using the in-app bearer token. */
final class LocalApi {
    private LocalApi() {}

    static Object call(String path, JSONObject body, String method) throws Exception {
        String token = Mobile.token();
        if (token.isEmpty()) throw new IOException(OrnService.error.isEmpty() ? "ORH 正在启动，请稍候" : OrnService.error);
        HttpURLConnection connection = (HttpURLConnection) new URL("http://127.0.0.1:4789/api/v1" + path).openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(20000);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Authorization", "Bearer " + token);
        try {
            if (body != null) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body.toString().getBytes(StandardCharsets.UTF_8));
                }
            }
            int code = connection.getResponseCode();
            InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
            StringBuilder content = new StringBuilder();
            try (BufferedReader input = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = input.readLine()) != null) content.append(line);
            }
            Object result = new JSONTokener(content.toString()).nextValue();
            if (code >= 400) {
                throw new IOException(result instanceof JSONObject ? ((JSONObject) result).optString("detail", "操作未完成") : "操作未完成");
            }
            return result;
        } finally {
            connection.disconnect();
        }
    }
}
