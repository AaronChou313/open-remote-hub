package top.openremotehub.client;

import java.io.*;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import java.net.*;
import java.nio.charset.StandardCharsets;
import org.json.*;
import top.openremotehub.client.core.mobile.Mobile;

/** Loopback client for the Go core's LocalAPI, using the in-app bearer token. */
final class LocalApi {
    private LocalApi() {}
    static final class ApiException extends IOException {
        final int status;
        ApiException(int status,String message) {super(message);this.status=status;}
    }

    static Object call(String path, JSONObject body, String method) throws Exception {
        String token = Mobile.token();
        if (token.isEmpty()) throw new IOException(MeshService.error.isEmpty() ? "ORH 正在启动，请稍候" : MeshService.error);
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
                throw new ApiException(code,result instanceof JSONObject ? ((JSONObject) result).optString("detail", "操作未完成") : "操作未完成");
            }
            return result;
        } finally {
            connection.disconnect();
        }
    }
    static String consoleURL(Context context,String deviceID,String ip,String name) throws Exception {
        JSONObject result=(JSONObject)call("/console",new JSONObject().put("peer_ip",ip).put("device_id",deviceID),"POST");
        String address=result.getString("url");
        Uri gateway=Uri.parse(address);
        SharedPreferences saved=context.getSharedPreferences("cloud",Context.MODE_PRIVATE);
        String token=saved.getString("token",""),base=saved.getString("url","");
        if(token.isEmpty()||base.isEmpty()) throw new IOException("账号会话已过期，请返回设置登录 ORH");
        try {
            JSONObject ticket=(JSONObject)call("/cloud/ticket",new JSONObject().put("device_id",deviceID)
                .put("address",gateway.getScheme()+"://"+gateway.getAuthority()).put("account_token",token),"POST");
            String link=ticket.getString("url");
            if(!link.contains("#")) throw new IOException("Cloud 未返回设备授权，请重新登录");
            address=address.replace("/auth/cloud/enter","/auth/cloud")+link.substring(link.indexOf('#'));
        } catch(ApiException failure) {
            if(failure.status<500) throw failure;
            Diagnostics.log("console-ticket","Cloud 暂时不可用，打开目标恢复登录");
            address=address.replace("/auth/cloud/enter","/");
        }
        return Uri.parse(address).buildUpon().appendQueryParameter("android_client","1")
            .appendQueryParameter("device_id",deviceID).appendQueryParameter("device_name",name).build().toString();
    }

}
