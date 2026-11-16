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
                throw new IOException(result instanceof JSONObject ? ((JSONObject) result).optString("detail", "操作未完成") : "操作未完成");
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
            JSONObject ticket=cloudTicket(base+"/api/devices/"+deviceID+"/ticket",token,
                new JSONObject().put("address",gateway.getScheme()+"://"+gateway.getAuthority()).put("state",""));
            String link=ticket.getString("url");
            if(!link.contains("#")) throw new IOException("Cloud 未返回设备授权，请重新登录");
            address=address.replace("/auth/cloud/enter","/auth/cloud")+link.substring(link.indexOf('#'));
        } catch(IOException failure) {
            if(failure.getMessage()!=null&&failure.getMessage().matches(".*Cloud 4[0-9][0-9].*")) throw failure;
            address=address.replace("/auth/cloud/enter","/");
        }
        return Uri.parse(address).buildUpon().appendQueryParameter("android_client","1")
            .appendQueryParameter("device_id",deviceID).appendQueryParameter("device_name",name).build().toString();
    }

    private static JSONObject cloudTicket(String address,String token,JSONObject body) throws Exception {
        HttpURLConnection connection=(HttpURLConnection)new URL(address).openConnection();
        connection.setConnectTimeout(8000);connection.setReadTimeout(12000);
        connection.setRequestMethod("POST");connection.setRequestProperty("Authorization","Bearer "+token);
        connection.setRequestProperty("Content-Type","application/json");connection.setDoOutput(true);
        try {
            try(OutputStream output=connection.getOutputStream()) {output.write(body.toString().getBytes(StandardCharsets.UTF_8));}
            int code=connection.getResponseCode();
            if(code>=400) throw new IOException("Cloud "+code+(code==401?"，请返回设置重新登录":""));
            StringBuilder text=new StringBuilder();
            try(BufferedReader reader=new BufferedReader(new InputStreamReader(connection.getInputStream(),StandardCharsets.UTF_8))) {
                String line;while((line=reader.readLine())!=null)text.append(line);
            }
            return new JSONObject(text.toString());
        } finally {connection.disconnect();}
    }

}
