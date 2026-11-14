package top.openremotehub.client;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.*;
import android.net.wifi.WifiManager;
import android.os.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;
import top.openremotehub.client.core.mobile.Mobile;

/** Owns the Go runtime while the Activity or RustDesk is in the foreground. */
public final class MeshService extends Service {
    static volatile String error = "";
    static volatile long heartbeat = 0;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback callback;
    private PowerManager.WakeLock connectionWakeLock;
    private WifiManager.WifiLock wifiLock;
    private NotificationManager notifications;
    private long desktopStartingUntil;
    private String lastNetwork = "";
    private String lastNotice = "";
    private boolean destroyed;
    private boolean pendingRestore;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable maintainConnection = this::checkConnections;

    /** True while this process still owns a live Go runtime and a recent heartbeat. */
    static boolean alive() {
        return heartbeat != 0 && SystemClock.elapsedRealtime() - heartbeat < 60_000;
    }

    /** Set while a forwarded session exists, and kept for a grace period across restarts. */
    static boolean desktopActive(Context context) {
        return context.getSharedPreferences("desktop", MODE_PRIVATE).getLong("until", 0) > System.currentTimeMillis();
    }

    private void checkConnections() {
        worker.execute(() -> {
            boolean connected = Mobile.activeForwards() > 0;
            main.post(() -> {
                if (destroyed) return;
                heartbeat = SystemClock.elapsedRealtime();
                if (connected || SystemClock.elapsedRealtime() < desktopStartingUntil) {
                    holdLocks();
                    getSharedPreferences("desktop", MODE_PRIVATE).edit().putLong("until", System.currentTimeMillis() + 300_000).apply();
                    notice(connected ? "远程桌面转发中，收尾时请返回 ORH 断开" : "ORH 正在运行，点击管理设备");
                } else {
                    releaseLocks();
                    notice("ORH 正在运行，点击管理设备");
                }
                main.postDelayed(maintainConnection, 15000);
            });
        });
    }

    private void holdLocks() {
        if (wifiLock != null && !wifiLock.isHeld()) {
            wifiLock.acquire();
            Diagnostics.log("power", "已持有 Wi-Fi 高性能锁");
        }
        if (connectionWakeLock != null) {
            boolean held = connectionWakeLock.isHeld();
            connectionWakeLock.acquire(90000);
            if (!held) Diagnostics.log("power", "已持有 CPU 唤醒锁");
        }
    }

    private void releaseLocks() {
        if (wifiLock != null && wifiLock.isHeld()) {
            wifiLock.release();
            Diagnostics.log("power", "已释放 Wi-Fi 高性能锁");
        }
        if (connectionWakeLock != null && connectionWakeLock.isHeld()) {
            connectionWakeLock.release();
            Diagnostics.log("power", "已释放 CPU 唤醒锁");
        }
    }

    private final Runnable rebind = () -> worker.execute(() -> {
        try {
            String value = networkInfo();
            if (value.equals(lastNetwork)) return;
            boolean initial = lastNetwork.isEmpty();
            lastNetwork = value;
            Diagnostics.log("network", (initial ? "初始网络 " : "网络变化 ") + networkSummary(value));
            Mobile.updateNetwork(value);
            if (!initial) Mobile.rebind();
        } catch (Exception e) {
            error = "网络切换后正在重连";
            Diagnostics.log("network", "网络更新失败: " + e);
        }
    });

    private static String networkSummary(String value) {
        try {
            JSONObject info = new JSONObject(value);
            JSONArray interfaces = info.optJSONArray("interfaces");
            String name = info.optString("default_interface");
            String gateway = info.optString("gateway");
            return name + (gateway.isEmpty() ? "" : " 网关 " + gateway) + " · " + (interfaces == null ? 0 : interfaces.length()) + " 个接口";
        } catch (JSONException error) {
            return "无法解析";
        }
    }

    @Override public void onCreate() {
        super.onCreate();
        Diagnostics.attach(this);
        Diagnostics.log("service", "服务创建");
        go.Seq.setContext(getApplicationContext());
        notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel("mesh", "组网连接", NotificationManager.IMPORTANCE_LOW));
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, notification("正在启动设备网络"), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        } else {
            startForeground(1, notification("正在启动设备网络"));
        }
        connectionWakeLock = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "OpenRemoteHub:Forwarding");
        connectionWakeLock.setReferenceCounted(false);
        WifiManager wifi = getSystemService(WifiManager.class);
        int mode = Build.VERSION.SDK_INT >= 29 ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
        wifiLock = wifi.createWifiLock(mode, "OpenRemoteHub:OrnWifi");
        wifiLock.setReferenceCounted(false);
        connectivity = getSystemService(ConnectivityManager.class);
        callback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) { scheduleRebind(); }
            @Override public void onLost(Network network) { scheduleRebind(); }
            @Override public void onLinkPropertiesChanged(Network network, LinkProperties properties) { scheduleRebind(); }
        };
        connectivity.registerDefaultNetworkCallback(callback);
        Watchdog.schedule(this, 60_000);
    }

    private Notification notification(String status) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, "mesh")
            .setSmallIcon(R.drawable.ic_orh).setContentTitle("ORH · 设备网络")
            .setContentText(status).setContentIntent(open).setOngoing(true).build();
    }

    private void notice(String status) {
        if (status.equals(lastNotice)) return;
        lastNotice = status;
        notifications.notify(1, notification(status));
    }

    private String networkInfo() throws JSONException {
        JSONObject result = new JSONObject();
        JSONArray interfaces = new JSONArray();
        Set<String> names = new HashSet<>();
        Network active = connectivity.getActiveNetwork();
        for (Network network : connectivity.getAllNetworks()) {
            LinkProperties link = connectivity.getLinkProperties(network);
            if (link == null || link.getInterfaceName() == null) continue;
            String name = link.getInterfaceName();
            if (network.equals(active)) {
                result.put("default_interface", name);
                for (RouteInfo route : link.getRoutes()) {
                    if (route.isDefaultRoute() && route.getGateway() != null) result.put("gateway", route.getGateway().getHostAddress());
                }
            }
            if (!names.add(name)) continue;
            JSONArray addresses = new JSONArray();
            for (LinkAddress address : link.getLinkAddresses()) {
                String ip = address.getAddress().getHostAddress().split("%", 2)[0];
                addresses.put(ip + "/" + address.getPrefixLength());
            }
            int mtu = Build.VERSION.SDK_INT >= 29 ? link.getMtu() : 1500;
            interfaces.put(new JSONObject().put("name", name).put("mtu", mtu > 0 ? mtu : 1500).put("addresses", addresses));
        }
        result.put("interfaces", interfaces);
        return result.toString();
    }

    private void scheduleRebind() {
        main.removeCallbacks(rebind);
        main.postDelayed(rebind, 1500);
    }

    @Override public int onStartCommand(Intent intent, int flags, int id) {
        // A null intent means Android restarted a killed service; only that path
        // restores the previous desktop endpoint on its own.
        if (intent == null || intent.getBooleanExtra("restore", false)) pendingRestore = true;
        if (intent != null && intent.getBooleanExtra("desktop", false)) {
            desktopStartingUntil = SystemClock.elapsedRealtime() + 90000;
            holdLocks();
        }
        worker.execute(this::startRuntime);
        return START_STICKY;
    }

    @Override public void onTaskRemoved(Intent rootIntent) {
        Diagnostics.log("service", "任务被移除，保持后台连接");
        super.onTaskRemoved(rootIntent);
    }

    @Override public void onTrimMemory(int level) {
        Diagnostics.log("memory", "系统内存压力级别 " + level);
        super.onTrimMemory(level);
    }

    @Override public void onLowMemory() {
        Diagnostics.log("memory", "系统低内存");
        super.onLowMemory();
    }

    private void startRuntime() {
        try {
            lastNetwork = networkInfo();
            Mobile.updateNetwork(lastNetwork);
            boolean fresh = Mobile.token().isEmpty();
            if (fresh) Diagnostics.log("core", "启动组网内核 " + networkSummary(lastNetwork));
            Mobile.start(new File(getFilesDir(), "mesh").getAbsolutePath(), Build.MANUFACTURER + " " + Build.MODEL);
            error = "";
            heartbeat = SystemClock.elapsedRealtime();
            if (fresh) {
                Diagnostics.log("core", "组网内核已启动");
                if (pendingRestore) new Thread(this::restoreSession, "mesh-restore").start();
            }
            pendingRestore = false;
            notice("ORH 正在运行，点击管理设备");
            main.post(() -> {
                if (destroyed) return;
                main.removeCallbacks(maintainConnection);
                main.post(maintainConnection);
            });
        } catch (Exception e) {
            error = "组网启动失败：" + e.getMessage();
            Diagnostics.log("core", error);
            android.util.Log.e("ORH", error);
            notice("启动失败，点击重试");
        }
    }

    /**
     * Re-creates the last desktop endpoint after a process restart. The saved
     * loopback port is stable, so RustDesk can reconnect without visiting the console.
     */
    private void restoreSession() {
        SharedPreferences saved = getSharedPreferences("desktop", MODE_PRIVATE);
        String ip = saved.getString("peer_ip", "");
        int remote = saved.getInt("remote_port", 0);
        int local = saved.getInt("local_port", 0);
        if (ip.isEmpty() || remote == 0 || System.currentTimeMillis() >= saved.getLong("until", 0)) return;
        for (int attempt = 0; attempt < 4; attempt++) {
            try {
                JSONObject result = call("/forwards", new JSONObject().put("peer_ip", ip).put("remote_port", remote).put("local_port", local));
                String address = "127.0.0.1:" + result.getJSONObject("forward").optInt("local_port", local);
                Diagnostics.log("desktop", "已恢复远程桌面转发 " + address);
                notifyRestored(address);
                return;
            } catch (Exception error) {
                Diagnostics.log("desktop", "恢复远程桌面转发失败（第 " + (attempt + 1) + " 次）: " + error.getMessage());
                try { Thread.sleep(4000); } catch (InterruptedException ignored) { return; }
            }
        }
    }

    private JSONObject call(String path, JSONObject body) throws Exception {
        String token = Mobile.token();
        if (token.isEmpty()) throw new IOException("组网内核尚未就绪");
        HttpURLConnection connection = (HttpURLConnection) new URL("http://127.0.0.1:4789/api/v1" + path).openConnection();
        connection.setConnectTimeout(5000); connection.setReadTimeout(20000); connection.setRequestMethod("POST");
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("Content-Type", "application/json");
        connection.setDoOutput(true);
        try {
            try (OutputStream output = connection.getOutputStream()) { output.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode();
            InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
            StringBuilder content = new StringBuilder();
            try (BufferedReader input = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = input.readLine()) != null) content.append(line);
            }
            Object result = new JSONTokener(content.toString()).nextValue();
            if (code >= 400) throw new IOException(result instanceof JSONObject ? ((JSONObject) result).optString("detail", "转发未恢复") : "转发未恢复");
            return (JSONObject) result;
        } finally {
            connection.disconnect();
        }
    }

    private void notifyRestored(String address) {
        Intent open = new Intent(Intent.ACTION_VIEW, MainActivity.rustDeskURI(address)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        Notification notification = new Notification.Builder(this, "mesh")
            .setSmallIcon(R.drawable.ic_orh).setContentTitle("远程桌面已恢复")
            .setContentText("点击重新连接 " + address).setContentIntent(PendingIntent.getActivity(this, 2, open, PendingIntent.FLAG_IMMUTABLE))
            .setAutoCancel(true).build();
        notifications.notify(2, notification);
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public void onDestroy() {
        Diagnostics.log("service", "服务销毁");
        destroyed = true;
        heartbeat = 0;
        connectivity.unregisterNetworkCallback(callback);
        main.removeCallbacks(rebind);
        main.removeCallbacks(maintainConnection);
        releaseLocks();
        worker.execute(() -> { try { Mobile.stop(); } catch (Exception ignored) {} });
        worker.shutdown();
        super.onDestroy();
    }
}
