package top.openremotehub.client;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import top.openremotehub.client.core.mobile.Mobile;

/** Native phone/tablet management UI, backed by the desktop's identical LocalAPI. */
public final class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newFixedThreadPool(2);
    private final Handler main = new Handler(Looper.getMainLooper());
    private LinearLayout page, binding;
    private TextView status, message;
    private Button backgroundButton;
    private String pendingDesktop;
    private GridLayout devices;
    private boolean busy, refreshing, active;
    private String previous = "";
    private String lastFailure = "";
    private long lastUptime = -1;
    private JSONArray directory;
    private long directoryAt;
    private final Runnable poll = new Runnable() {
        @Override public void run() { if (active) { refresh(); main.postDelayed(this,5000); } }
    };
    interface Work { void run() throws Exception; }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        Diagnostics.attach(this);
        Diagnostics.log("ui","页面创建");
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},1);
        startForegroundService(new Intent(this,MeshService.class));
        build();
    }
    private int dp(int value) { return Math.round(value*getResources().getDisplayMetrics().density); }
    private int color(int resource) { return getColor(resource); }
    private TextView text(String value,int size,boolean bold) {
        TextView view = new TextView(this);
        view.setText(value); view.setTextSize(size); view.setTextColor(color(R.color.text));
        if (bold) view.setTypeface(null,Typeface.BOLD);
        view.setPadding(0,dp(4),0,dp(4));
        return view;
    }
    private LinearLayout column() {
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); return layout;
    }
    private LinearLayout card() {
        LinearLayout layout = column(); layout.setPadding(dp(20),dp(16),dp(20),dp(16));
        GradientDrawable background = new GradientDrawable();
        background.setColor(color(R.color.card)); background.setCornerRadius(dp(16));
        background.setStroke(dp(1),color(R.color.outline)); layout.setBackground(background);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1,-2); params.bottomMargin = dp(16);
        layout.setLayoutParams(params); return layout;
    }
    private Button button(String label,Work work) {
        Button button = new Button(this); button.setText(label); button.setAllCaps(false);
        button.setOnClickListener(view -> perform(button,work)); return button;
    }
    private void build() {
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        scroll.setBackgroundColor(color(R.color.surface));
        page = column(); page.setPadding(dp(20),dp(24),dp(20),dp(24)); scroll.addView(page);
        page.addView(text("ORH",14,true)); page.addView(text("设备网络",30,true));
        LinearLayout self = card(); status = text("正在启动组网…",17,true); self.addView(status);
        LinearLayout controls = new LinearLayout(this);
        controls.addView(button("重新连接",() -> {Mobile.start(new File(getFilesDir(),"mesh").getAbsolutePath(),Build.MANUFACTURER+" "+Build.MODEL); api("/control",new JSONObject().put("action","reconnect"),"POST"); onUI(() -> info("已请求重新连接"));}));
        controls.addView(button("刷新",() -> {}));
        self.addView(controls); page.addView(self);
        backgroundButton=button("允许后台连接",() -> onUI(() -> requestBackground(null)));
        self.addView(backgroundButton);
        message = text("",14,false); message.setTextColor(color(R.color.muted)); page.addView(message);
        binding = card(); page.addView(binding);
        devices = new GridLayout(this); page.addView(devices);
        LinearLayout options = new LinearLayout(this);
        options.addView(button("网络诊断",() -> {
            Object result=api("/netcheck",new JSONObject(),"POST");
            onUI(() -> {if (active) new AlertDialog.Builder(this).setTitle("网络诊断").setMessage(result.toString()).setPositiveButton("关闭",null).show();});
        }));
        Button leave = new Button(this); leave.setText("退出网络"); leave.setAllCaps(false);
        leave.setOnClickListener(view -> new AlertDialog.Builder(this).setTitle("退出当前网络？")
            .setMessage("移除此设备的账号绑定和网络身份。重新连接需要绑定账号。")
            .setNegativeButton("取消",null).setPositiveButton("退出",(dialog,which) -> perform(leave,() -> {
                api("/leave",new JSONObject().put("confirm",true),"POST");
                getSharedPreferences("desktop",MODE_PRIVATE).edit().clear().apply();
            })).show());
        Button diagnose=new Button(this); diagnose.setText("连接诊断"); diagnose.setAllCaps(false);
        diagnose.setOnClickListener(view -> diagnose());
        options.addView(diagnose);
        options.addView(button("厂商后台设置",() -> openVendorSettings()));
        options.addView(leave); page.addView(options);
        setContentView(scroll);
        // Keep controls clear of status/navigation bars under Android 15 edge-to-edge.
        scroll.setOnApplyWindowInsetsListener((view,insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars());
                view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
            } else {
                view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
    }
    @Override public void onResume() {
        super.onResume(); active=true;
        Diagnostics.log("ui","页面恢复");
        backgroundButton.setVisibility(backgroundAllowed()?View.GONE:View.VISIBLE);
        onUI(poll);
    }
    @Override public void onPause() { active=false; main.removeCallbacks(poll); Diagnostics.log("ui","页面暂停"); super.onPause(); }
    @Override public void onDestroy() { Diagnostics.log("ui","页面销毁"); worker.shutdownNow(); super.onDestroy(); }
    private Object api(String path,JSONObject body,String method) throws Exception {
        return LocalApi.call(path,body,method);
    }
    private void perform(Button button,Work work) {
        if (busy) return; busy=true; button.setEnabled(false);
        worker.execute(() -> {
            try { work.run(); }
            catch (Exception error) { onUI(() -> info(error.getMessage())); }
            finally { onUI(() -> { busy=false; button.setEnabled(true); previous=""; refresh(); }); }
        });
    }
    private void onUI(Runnable work) {
        main.post(() -> {if (!isDestroyed()&&!isFinishing()) work.run();});
    }
    private void info(String value) { message.setText(value); }
    private void refresh() {
        if (busy||refreshing||!active) return;
        refreshing=true;
        worker.execute(() -> {
            try {
                JSONObject self=(JSONObject)api("/status",null,"GET");
                JSONArray peers=(JSONArray)api("/peers",null,"GET");
                JSONArray forwards=(JSONArray)api("/forwards",null,"GET");
                JSONArray directory=cloudDirectory();
                String snapshot=self.toString()+peers.toString()+forwards.toString()+(directory==null?"":"d"+directory.toString());
                long uptime=self.optLong("uptime_seconds",-1);
                onUI(() -> {
                    if (busy) return;
                    if (lastUptime>=0&&uptime>=0&&uptime<lastUptime)
                        Diagnostics.log("core","检测到组网内核重启，运行时长由 "+lastUptime+" 秒变为 "+uptime+" 秒");
                    lastUptime=uptime;
                    if (!lastFailure.isEmpty()) { info(""); lastFailure=""; }
                    if (!snapshot.equals(previous)) { render(self,peers,forwards,uptime,directory); previous=snapshot; }
                });
            } catch (Exception error) { onUI(() -> {lastFailure=error.getMessage(); info(lastFailure);}); }
            finally { onUI(() -> refreshing=false); }
        });
    }
    private String ips(JSONObject peer) {
        JSONArray addresses=peer.optJSONArray("ips");
        return addresses!=null&&addresses.length()>0?addresses.optString(0):"等待分配地址";
    }
    private static String duration(long seconds) {
        if (seconds<60) return seconds+" 秒";
        if (seconds<3600) return (seconds/60)+" 分 "+(seconds%60)+" 秒";
        return (seconds/3600)+" 小时 "+((seconds%3600)/60)+" 分";
    }
    /** Cloud directory changes slowly; refresh it at most once a minute. */
    private JSONArray cloudDirectory() {
        if (directory!=null&&System.currentTimeMillis()-directoryAt<60000) return directory;
        try {
            directory=(JSONArray)api("/directory",null,"GET");
            directoryAt=System.currentTimeMillis();
            return directory;
        } catch (Exception unavailable) {
            return directory;
        }
    }
    /** Cloud directory tells which mesh IPs publish an ORH console (8765). */
    private static boolean consoleAvailable(JSONArray directory,String ip) {
        if (directory==null) return true;
        for (int index=0;index<directory.length();index++) {
            JSONObject device=directory.optJSONObject(index);
            JSONObject mesh=device==null?null:device.optJSONObject("mesh");
            if (mesh==null) continue;
            JSONArray ips=mesh.optJSONArray("ips");
            boolean matches=false;
            for (int item=0;ips!=null&&item<ips.length();item++) if (ip.equals(ips.optString(item))) matches=true;
            if (!matches) continue;
            JSONArray services=mesh.optJSONArray("services");
            for (int item=0;services!=null&&item<services.length();item++) if (services.optInt(item)==8765) return true;
            return false;
        }
        return true;
    }
    private void render(JSONObject self,JSONArray peers,JSONArray forwards,long uptime,JSONArray directory) {
        JSONObject device=self.optJSONObject("device");
        int connections=0;
        for (int index=0;index<forwards.length();index++) connections+=forwards.optJSONObject(index).optInt("connections");
        String line=(device==null?"":ips(device))+" · "+("Running".equals(self.optString("backend_state"))?"已连接":self.optString("backend_state"));
        if (uptime>=0) line+=" · 运行 "+duration(uptime);
        if (connections>0) line+=" · "+connections+" 个连接";
        status.setText((device==null?"此设备":device.optString("hostname"))+"\n"+line);
        JSONObject cloud=self.optJSONObject("cloud");
        binding.removeAllViews();
        boolean bound=cloud!=null&&cloud.optBoolean("bound"); binding.setVisibility(bound?View.GONE:View.VISIBLE);
        if (!bound) {
            binding.addView(text("绑定 Cloud 账号",18,true));
            if (cloud!=null&&cloud.has("pending")) {
                JSONObject pending=cloud.optJSONObject("pending");
                binding.addView(text(pending.optString("user_code"),24,true));
                binding.addView(button("前往 Cloud 确认绑定",() -> onUI(() -> open(pending.optString("verification_url")))));
            } else {
                binding.addView(button("绑定账号",() -> api("/cloud/bind",new JSONObject().put("cloud_url","https://cloud.openremotehub.top"),"POST")));
            }
        }
        if (cloud!=null&&!cloud.optString("error").isEmpty()) info(cloud.optString("error"));
        devices.removeAllViews();
        int columns=getResources().getConfiguration().screenWidthDp>=720?2:1;
        devices.setColumnCount(columns);
        for (int index=0;index<peers.length();index++) {
            JSONObject peer=peers.optJSONObject(index); if (peer==null) continue;
            LinearLayout entry=card();
            GridLayout.LayoutParams params=new GridLayout.LayoutParams();
            params.width=0; params.columnSpec=GridLayout.spec(GridLayout.UNDEFINED,1f);
            params.setMargins(dp(4),0,dp(4),dp(14)); entry.setLayoutParams(params);
            entry.addView(text(peer.optString("hostname"),20,true));
            TextView detail=text(ips(peer)+" · "+(peer.optBoolean("online")?"在线":"离线"),14,false);
            detail.setTextColor(color(R.color.muted)); entry.addView(detail);
            String path=peer.optString("path");
            entry.addView(text("direct".equals(path)?"直连":"relay".equals(path)?"中继":"待连接",14,true));
            String ip=ips(peer);
            boolean console=consoleAvailable(directory,ip);
            if (!console) detail.setText(detail.getText()+" · 仅远程桌面");
            LinearLayout actions=new LinearLayout(this);
            actions.addView(button("检测",() -> {
                JSONObject result=(JSONObject)api("/ping",new JSONObject().put("peer_ip",ip),"POST");
                onUI(() -> info(result.optString("Err").isEmpty()?peer.optString("hostname")+" · "+Math.round(result.optDouble("LatencySeconds")*1000)+" ms":result.optString("Err")));
            }));
            Button consoleButton=button("控制台",() -> {
                JSONObject result=(JSONObject)api("/console",new JSONObject().put("peer_ip",ip),"POST");
                onUI(() -> openConsole(result.optString("url"),ip,peer.optString("hostname")));
            });
            consoleButton.setEnabled(console);
            actions.addView(consoleButton);
            entry.addView(actions);
            Button desktop=button("远程桌面",() -> {
                String address=desktopAddress(ip);
                onUI(() -> desktop(address));
            });
            desktop.setEnabled(peer.optBoolean("online")); entry.addView(desktop); devices.addView(entry);
        }
        if (peers.length()==0) devices.addView(text("将其他设备绑定到同一账号后显示在这里。",15,false));
    }
    private void openConsole(String url,String ip,String name) {
        Diagnostics.log("console","打开 "+name+" · "+url);
        startActivity(new Intent(this,ConsoleActivity.class)
            .putExtra("url",url).putExtra("peer_ip",ip).putExtra("name",name));
    }
    private void open(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url))); }
        catch (ActivityNotFoundException error) { info("此设备没有可用的浏览器"); }
    }
    static Uri rustDeskURI(String address) {
        // RustDesk reads Dart Uri.path directly, so keep the port colon literal.
        return Uri.parse("rustdesk://connection/new/"+address);
    }
    /** Keeps the endpoint stable so a restarted core can rebuild the same forward. */
    private void remember(SharedPreferences saved,String ip,int port) {
        saved.edit().putInt(ip,port).putString("peer_ip",ip).putInt("remote_port",21118).putInt("local_port",port).putLong("until",System.currentTimeMillis()+600000).apply();
    }
    String desktopAddress(String ip) throws Exception {
        SharedPreferences saved=getSharedPreferences("desktop",MODE_PRIVATE);
        JSONArray forwards=(JSONArray)api("/forwards",null,"GET");
        for (int index=0;index<forwards.length();index++) {
            JSONObject entry=forwards.getJSONObject(index);
            if (entry.optString("kind").equals("tcp") && entry.optString("peer_ip").equals(ip) && entry.optInt("remote_port")==21118) {
                int port=entry.getInt("local_port");
                remember(saved,ip,port);
                return "127.0.0.1:"+port;
            }
        }
        JSONObject result=(JSONObject)api("/forwards",new JSONObject().put("peer_ip",ip).put("remote_port",21118).put("local_port",saved.getInt(ip,0)),"POST");
        remember(saved,ip,result.getJSONObject("forward").getInt("local_port"));
        return result.getString("address");
    }
    private boolean backgroundAllowed() {
        return getSystemService(PowerManager.class).isIgnoringBatteryOptimizations(getPackageName());
    }
    private void requestBackground(String address) {
        pendingDesktop=address;
        getPreferences(MODE_PRIVATE).edit().putBoolean("background_requested",true).apply();
        try {
            startActivityForResult(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,Uri.parse("package:"+getPackageName())),2);
        } catch (ActivityNotFoundException error) {
            startActivityForResult(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),2);
        }
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if (request==2 && pendingDesktop!=null) {
            String address=pendingDesktop;
            pendingDesktop=null;
            openDesktop(address);
        }
    }
    private void desktop(String address) {
        if (!backgroundAllowed() && !getPreferences(MODE_PRIVATE).getBoolean("background_requested",false)) {
            requestBackground(address);
            return;
        }
        openDesktop(address);
    }
    private void openDesktop(String address) {
        Diagnostics.log("desktop","发起远程桌面 "+address);
        getSharedPreferences("desktop",MODE_PRIVATE).edit().putLong("until",System.currentTimeMillis()+600000).apply();
        startForegroundService(new Intent(this,MeshService.class).putExtra("desktop",true));
        Uri uri=rustDeskURI(address);
        try { startActivity(new Intent(Intent.ACTION_VIEW,uri)); }
        catch (ActivityNotFoundException error) {
            Diagnostics.log("desktop","未安装 RustDesk，已复制地址");
            getSystemService(ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("组网连接地址",address));
            new AlertDialog.Builder(this).setTitle("打开 RustDesk").setMessage("请安装 RustDesk。连接地址已复制："+address).setPositiveButton("关闭",null).show();
        }
    }
    /** Some OEM builds keep killing background services regardless of the standard exemption. */
    private void openVendorSettings() {
        Diagnostics.log("ui","打开厂商后台设置");
        String[][] targets={
            {"com.vivo.permissionmanager","com.vivo.permissionmanager.activity.BgStartUpManagerActivity"},
            {"com.iqoo.secure","com.iqoo.secure.ui.phoneoptimize.BgStartUpManager"},
            {"com.miui.securitycenter","com.miui.permcenter.autostart.AutoStartManagementActivity"},
            {"com.coloros.safecenter","com.coloros.safecenter.permission.startup.StartupAppListActivity"},
        };
        for (String[] target:targets) {
            try {
                Intent intent=new Intent().setComponent(new android.content.ComponentName(target[0],target[1]))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (getPackageManager().resolveActivity(intent,0)!=null) { startActivity(intent); return; }
            } catch (Exception ignored) {}
        }
        try {
            startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName())));
        } catch (Exception error) {
            info("请在系统设置中允许 ORH 后台运行与高耗电");
        }
    }
    private void diagnose() {
        if (busy) return;
        busy=true;
        worker.execute(() -> {
            StringBuilder report=new StringBuilder();
            try {
                JSONObject value=(JSONObject)api("/diagnostics",null,"GET");
                JSONArray forwards=value.optJSONArray("forwards");
                JSONArray peers=value.optJSONArray("peers");
                report.append("组网 ").append(value.optString("version")).append(" · ").append(value.optString("platform")).append("\n");
                report.append("内核运行 ").append(duration(value.optLong("uptime_seconds",0))).append(" · 协程 ").append(value.optInt("goroutines")).append("\n");
                report.append("组网 ").append(value.optString("backend_state")).append(value.optString("mesh_error").isEmpty()?"":" · "+value.optString("mesh_error")).append("\n");
                if (peers!=null) for (int index=0;index<peers.length();index++) {
                    JSONObject peer=peers.optJSONObject(index);
                    report.append("设备 ").append(peer.optString("hostname")).append(" · ").append(peer.optString("path").isEmpty()?"idle":peer.optString("path")).append(peer.optBoolean("online")?" · 在线":" · 离线").append("\n");
                }
                report.append("转发 ").append(forwards==null?0:forwards.length()).append(" 个\n");
                if (forwards!=null) for (int index=0;index<forwards.length();index++) {
                    JSONObject entry=forwards.optJSONObject(index);
                    report.append("  ").append(entry.optString("peer_ip")).append(":").append(entry.optInt("remote_port"))
                        .append("→").append(entry.optInt("local_port")).append(" · ").append(entry.optInt("connections")).append(" 连接 · 下行 ")
                        .append(entry.optLong("bytes_in")).append(" B · 上行 ").append(entry.optLong("bytes_out")).append(" B\n");
                    if (!entry.optString("last_error").isEmpty()) report.append("  错误 ").append(entry.optString("last_error")).append("\n");
                }
            } catch (Exception error) {
                report.append("本机内核不可用：").append(error.getMessage()).append("\n");
            }
            report.append("\n--- 设备日志 ---\n").append(Diagnostics.tail(5000));
            String body=report.toString();
            onUI(() -> {
                busy=false;
                new AlertDialog.Builder(this).setTitle("连接诊断").setMessage(body)
                    .setPositiveButton("复制",(dialog,which) -> {
                        getSystemService(ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("组网连接诊断",body));
                        info("诊断信息已复制");
                    }).setNegativeButton("关闭",null).show();
            });
        });
    }
}
