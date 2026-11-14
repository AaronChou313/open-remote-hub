package top.openremotehub.client;

import android.Manifest;
import android.app.*;
import android.app.usage.UsageStatsManager;
import android.content.*;
import android.graphics.Color;
import android.graphics.Outline;
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
    private TextView status, message, selfDetail, selfChip, selfDot, updateBanner, powerNotice;
    private EditText cloudAddress, cloudUser, cloudPassword;
    private Button cloudLoginButton;
    private String latestUpdateUrl = "";
    private boolean boundBefore;
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

    private TextView muted(String value) {
        TextView view = text(value, 13, false); view.setTextColor(color(R.color.muted)); return view;
    }
    private TextView section(String value) {
        TextView view = text(value, 12, true); view.setTextColor(color(R.color.muted));
        view.setPadding(0, dp(18), 0, dp(6)); return view;
    }
    private TextView chip(String value) {
        TextView view = new TextView(this);
        view.setText(value); view.setTextSize(11); view.setTextColor(color(R.color.accent));
        view.setPadding(dp(8), dp(3), dp(8), dp(3));
        GradientDrawable background = new GradientDrawable();
        background.setColor(color(R.color.accentSoft)); background.setCornerRadius(dp(20));
        view.setBackground(background);
        return view;
    }
    private Button primary(String label, Work work) {
        Button button = button(label, work);
        GradientDrawable background = new GradientDrawable();
        background.setColor(color(R.color.accent)); background.setCornerRadius(dp(12));
        button.setBackground(background); button.setTextColor(Color.WHITE);
        button.setTypeface(null, Typeface.BOLD); button.setTextSize(14);
        button.setPadding(dp(18), dp(10), dp(18), dp(10));
        return button;
    }
    private Button secondary(String label, Work work) {
        Button button = button(label, work);
        button.setTextSize(13);
        return button;
    }
    private void copy(String value) {
        getSystemService(ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("ORH 绑定码", value));
        info("绑定码已复制");
    }
    private static String stateLabel(String value) {
        switch (value) {
            case "Running": return "已连接";
            case "Starting": return "连接中";
            case "NeedsLogin": return "需要登录";
            case "NeedsMachineAuth": return "等待批准";
            case "Stopped": return "已断开";
            case "NoState": return "初始化";
            default: return value.isEmpty() ? "连接中" : value;
        }
    }
    private String versionName() {
        try { return getPackageManager().getPackageInfo(getPackageName(),0).versionName; }
        catch (Exception error) { return ""; }
    }
    private void checkForUpdate(boolean manual) {
        Updates.check(worker, main, versionName(), release -> {
            if (!active) return;
            if (release == null) {
                updateBanner.setVisibility(View.GONE);
                if (manual) info("已是最新版本 " + versionName());
                return;
            }
            latestUpdateUrl = release.url;
            updateBanner.setText("新版本 " + release.version + " · 更新");
            updateBanner.setVisibility(View.VISIBLE);
            if (manual) new AlertDialog.Builder(this).setTitle("发现新版本 " + release.version)
                .setMessage(release.notes.isEmpty() ? "可以下载安装新版本。" : release.notes)
                .setPositiveButton("下载", (dialog, which) -> open(release.url))
                .setNegativeButton("稍后", null).show();
            else info("新版本 " + release.version + " 可用");
        });
    }
    private EditText field(String hint, boolean secret) {
        EditText input = new EditText(this);
        input.setHint(hint); input.setTextSize(14); input.setSingleLine(true);
        if (secret) input.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        GradientDrawable background = new GradientDrawable();
        background.setColor(color(R.color.surface)); background.setCornerRadius(dp(9));
        background.setStroke(dp(1), color(R.color.outline));
        input.setBackground(background); input.setPadding(dp(12), dp(10), dp(12), dp(10));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1,-2); params.bottomMargin = dp(8);
        input.setLayoutParams(params);
        return input;
    }
    private void buildLoginCard() {
        binding.addView(text("登录 Cloud 账号", 20, true));
        binding.addView(muted("登录后自动注册这台设备并接入组网，不再需要绑定码。"));
        cloudAddress = field("Cloud 服务地址", false);
        cloudAddress.setText("https://cloud.openremotehub.top");
        cloudUser = field("账号", false);
        cloudPassword = field("密码", true);
        binding.addView(cloudAddress); binding.addView(cloudUser); binding.addView(cloudPassword);
        LinearLayout row = new LinearLayout(this);
        cloudLoginButton = primary("登录并绑定", () -> {});
        cloudLoginButton.setOnClickListener(view -> loginCloud());
        row.addView(cloudLoginButton);
        row.addView(secondary("注册账号", () -> {
            String base = cloudAddress.getText().toString().trim().replaceAll("/+$", "");
            if (!base.isEmpty()) open(base + "/");
        }));
        binding.addView(row);
    }
    private void loginCloud() {
        if (busy) return;
        String base = cloudAddress.getText().toString().trim();
        String user = cloudUser.getText().toString().trim();
        String password = cloudPassword.getText().toString();
        if (base.isEmpty() || user.isEmpty() || password.isEmpty()) { info("请输入 Cloud 地址、账号与密码"); return; }
        busy = true; cloudLoginButton.setEnabled(false);
        Diagnostics.log("cloud", "登录 " + base + " · " + user);
        worker.execute(() -> {
            try {
                JSONObject result = (JSONObject) api("/cloud/login",
                    new JSONObject().put("cloud_url", base).put("username", user).put("password", password), "POST");
                getSharedPreferences("cloud",MODE_PRIVATE).edit()
                    .putString("token",result.optString("account_token"))
                    .putString("url",base)
                    .putString("user",result.optString("username")).apply();
                onUI(() -> {
                    cloudPassword.setText("");
                    info("已登录 " + result.optString("username") + "，正在入网…");
                    previous = ""; refresh();
                });
            } catch (Exception error) {
                onUI(() -> info(error.getMessage()));
            } finally {
                onUI(() -> { busy = false; cloudLoginButton.setEnabled(true); });
            }
        });
    }
    private void build() {
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        scroll.setBackgroundColor(color(R.color.surface));
        page = column(); page.setPadding(dp(20),dp(24),dp(20),dp(24)); scroll.addView(page);

        LinearLayout brand = new LinearLayout(this); brand.setOrientation(LinearLayout.HORIZONTAL); brand.setGravity(Gravity.CENTER_VERTICAL);
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.orh_logo);
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(dp(30), dp(30)); logoParams.rightMargin = dp(9);
        logo.setLayoutParams(logoParams); logo.setClipToOutline(true);
        logo.setOutlineProvider(new ViewOutlineProvider() {
            @Override public void getOutline(View view, Outline outline) {
                outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), dp(8));
            }
        });
        brand.addView(logo);
        TextView mark = text("ORH",15,true); mark.setTextColor(color(R.color.accent)); mark.setLetterSpacing(0.14f); brand.addView(mark);
        updateBanner = text("",12,false); updateBanner.setTextColor(color(R.color.accent)); updateBanner.setGravity(Gravity.END);
        updateBanner.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1f)); updateBanner.setVisibility(View.GONE);
        updateBanner.setOnClickListener(view -> { if (!latestUpdateUrl.isEmpty()) open(latestUpdateUrl); });
        brand.addView(updateBanner); page.addView(brand);
        page.addView(text("设备网络",30,true));
        powerNotice = text("",13,false); powerNotice.setTextColor(Color.WHITE);
        GradientDrawable warn = new GradientDrawable(); warn.setColor(color(R.color.warn)); warn.setCornerRadius(dp(10));
        powerNotice.setBackground(warn); powerNotice.setPadding(dp(14),dp(10),dp(14),dp(10));
        powerNotice.setVisibility(View.GONE);
        LinearLayout.LayoutParams noticeParams = new LinearLayout.LayoutParams(-1,-2); noticeParams.bottomMargin = dp(12);
        powerNotice.setLayoutParams(noticeParams);
        powerNotice.setOnClickListener(view -> requestBackground(null));
        page.addView(powerNotice);

        LinearLayout self = card();
        LinearLayout head = new LinearLayout(this); head.setOrientation(LinearLayout.HORIZONTAL); head.setGravity(Gravity.CENTER_VERTICAL);
        selfDot = text("●",13,false); selfDot.setTextColor(color(R.color.muted)); selfDot.setPadding(0,0,dp(7),0); head.addView(selfDot);
        status = text("正在启动组网…",18,true); status.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1f)); head.addView(status);
        selfChip = chip("连接中"); head.addView(selfChip); self.addView(head);
        selfDetail = text("",13,false); selfDetail.setTextColor(color(R.color.muted)); self.addView(selfDetail);
        LinearLayout controls = new LinearLayout(this);
        controls.addView(primary("重新连接", () -> {
            Mobile.start(new File(getFilesDir(),"mesh").getAbsolutePath(),Build.MANUFACTURER+" "+Build.MODEL);
            api("/control",new JSONObject().put("action","reconnect"),"POST");
            onUI(() -> info("已请求重新连接"));
        }));
        Button refreshButton = secondary("刷新", () -> {});
        refreshButton.setOnClickListener(view -> refresh());
        controls.addView(refreshButton);
        self.addView(controls);
        backgroundButton = secondary("允许后台连接", () -> onUI(() -> requestBackground(null)));
        self.addView(backgroundButton);
        page.addView(self);

        message = text("",13,false); message.setTextColor(color(R.color.muted)); page.addView(message);
        binding = card(); page.addView(binding); buildLoginCard();
        page.addView(section("设备"));
        devices = new GridLayout(this); page.addView(devices);

        page.addView(section("更多"));
        GridLayout options = new GridLayout(this); options.setColumnCount(3);
        Button leave = secondary("解绑设备", () -> {});
        leave.setOnClickListener(view -> new AlertDialog.Builder(this).setTitle("解绑这台设备？")
            .setMessage("将删除本机在 Cloud 的设备条目与组网身份，控制台和远程桌面需要重新绑定后才能使用。")
            .setNegativeButton("取消",null).setPositiveButton("解绑",(dialog,which) -> perform(leave,() -> {
                api("/leave",new JSONObject().put("confirm",true),"POST");
                getSharedPreferences("desktop",MODE_PRIVATE).edit().clear().apply();
            })).show());
        Button netcheck = secondary("网络诊断", () -> {
            Object result=api("/netcheck",new JSONObject(),"POST");
            onUI(() -> {if (active) new AlertDialog.Builder(this).setTitle("网络诊断").setMessage(result.toString()).setPositiveButton("关闭",null).show();});
        });
        for (Button action : new Button[]{netcheck, secondary("连接诊断", this::diagnose), secondary("检查更新", () -> checkForUpdate(true)), secondary("厂商后台设置", this::openVendorSettings), leave}) {
            GridLayout.LayoutParams params = new GridLayout.LayoutParams();
            params.width = 0; params.columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f);
            params.setMargins(dp(2), dp(2), dp(2), dp(2));
            options.addView(action, params);
        }
        page.addView(options);
        setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((view,insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars());
                view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
            } else {
                view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
        checkForUpdate(false);
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
        boolean running="Running".equals(self.optString("backend_state"));
        status.setText(device==null?"此设备":device.optString("hostname"));
        selfDot.setTextColor(color(running?R.color.success:R.color.muted));
        selfChip.setText(stateLabel(self.optString("backend_state")));
        String line=(device==null?"":ips(device));
        if (!running && !self.optString("backend_state").isEmpty()) line+=" · "+stateLabel(self.optString("backend_state"));
        if (uptime>=0) line+=" · 运行 "+duration(uptime);
        if (connections>0) line+=" · "+connections+" 个连接";
        selfDetail.setText(line);
        powerNotice.setText("后台连接未授权，远程桌面可能被系统中断 · 点此授权");
        powerNotice.setVisibility(backgroundAllowed()?View.GONE:View.VISIBLE);
        JSONObject cloud=self.optJSONObject("cloud");
        boolean bound=cloud!=null&&cloud.optBoolean("bound");
        if (bound&&!boundBefore) info("已绑定 Cloud 账号");
        boundBefore=bound;
        binding.setVisibility(bound?View.GONE:View.VISIBLE);
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
            LinearLayout head=new LinearLayout(this); head.setOrientation(LinearLayout.HORIZONTAL); head.setGravity(Gravity.CENTER_VERTICAL);
            TextView dot=text("●",12,false); dot.setTextColor(color(peer.optBoolean("online")?R.color.success:R.color.muted));
            dot.setPadding(0,0,dp(7),0); head.addView(dot);
            TextView name=text(peer.optString("hostname"),19,true); name.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1f)); head.addView(name);
            String path=peer.optString("path");
            head.addView(chip("direct".equals(path)?"直连":"relay".equals(path)?"中继":"待连接"));
            entry.addView(head);
            TextView detail=text(ips(peer)+(peer.optBoolean("online")?" · 在线":" · 离线"),13,false);
            detail.setTextColor(color(R.color.muted)); entry.addView(detail);
            String ip=ips(peer);
            boolean console=consoleAvailable(directory,ip);
            if (!console) detail.setText(detail.getText()+" · 仅远程桌面");
            LinearLayout actions=new LinearLayout(this);
            actions.addView(secondary("检测", () -> {
                JSONObject result=(JSONObject)api("/ping",new JSONObject().put("peer_ip",ip),"POST");
                onUI(() -> info(result.optString("Err").isEmpty()?peer.optString("hostname")+" · "+Math.round(result.optDouble("LatencySeconds")*1000)+" ms":result.optString("Err")));
            }));
            Button consoleButton=secondary("控制台", () -> {
                JSONObject result=(JSONObject)api("/console",new JSONObject().put("peer_ip",ip),"POST");
                String address=result.optString("url");
                String ticket=ticketFor(ip);
                if (ticket!=null && ticket.contains("#")) address=address.replace("/auth/cloud/enter","/auth/cloud")+ticket.substring(ticket.indexOf('#'));
                final String target=address;
                onUI(() -> openConsole(target,ip,peer.optString("hostname")));
            });
            consoleButton.setEnabled(console);
            actions.addView(consoleButton);
            entry.addView(actions);
            Button desktop=primary("远程桌面", () -> {
                String address=desktopAddress(ip);
                onUI(() -> desktop(address));
            });
            desktop.setEnabled(peer.optBoolean("online")); entry.addView(desktop); devices.addView(entry);
        }
        if (peers.length()==0) {
            TextView empty=text("还没有其他设备。\n把另一台电脑或平板绑定到同一账号后会显示在这里。",14,false);
            empty.setTextColor(color(R.color.muted)); devices.addView(empty);
        }
    }
    private String ticketFor(String peerIp) {
        try {
            SharedPreferences saved=getSharedPreferences("cloud",MODE_PRIVATE);
            String token=saved.getString("token",""), base=saved.getString("url","");
            if (token.isEmpty() || base.isEmpty()) return null;
            JSONArray devices=(JSONArray)cloudCall(base+"/api/devices",token,"GET",null);
            String id=null;
            for (int index=0;index<devices.length() && id==null;index++) {
                JSONObject device=devices.optJSONObject(index); if (device==null) continue;
                JSONObject mesh=device.optJSONObject("mesh"); JSONArray ips=mesh==null?null:mesh.optJSONArray("ips");
                for (int item=0;ips!=null&&item<ips.length();item++) if (peerIp.equals(ips.optString(item))) id=device.optString("instance_id");
            }
            if (id==null || id.isEmpty()) return null;
            JSONObject ticket=(JSONObject)cloudCall(base+"/api/devices/"+id+"/ticket",token,"POST",new JSONObject().put("address","http://"+peerIp+":8765").put("state",""));
            return ticket.optString("url");
        } catch (Exception error) {
            Diagnostics.log("console","票据获取失败，使用网页授权："+error.getMessage());
            return null;
        }
    }
    private Object cloudCall(String address,String token,String method,JSONObject body) throws Exception {
        java.net.HttpURLConnection connection=(java.net.HttpURLConnection)new java.net.URL(address).openConnection();
        connection.setRequestMethod(method);
        connection.setRequestProperty("Authorization","Bearer "+token);
        connection.setConnectTimeout(8000); connection.setReadTimeout(12000);
        if (body!=null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type","application/json");
            try (java.io.OutputStream output=connection.getOutputStream()) {
                output.write(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            }
        }
        int code=connection.getResponseCode();
        java.io.InputStream input=code<400?connection.getInputStream():connection.getErrorStream();
        StringBuilder text=new StringBuilder();
        try (java.io.BufferedReader reader=new java.io.BufferedReader(new java.io.InputStreamReader(input,java.nio.charset.StandardCharsets.UTF_8))) {
            String line; while ((line=reader.readLine())!=null) text.append(line);
        }
        if (code>=400) throw new Exception("Cloud "+code);
        String value=text.toString().trim();
        return value.startsWith("[")?new JSONArray(value):new JSONObject(value);
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
        if (!backgroundAllowed()) {
            Diagnostics.log("desktop","后台未豁免，提示授权");
            new AlertDialog.Builder(this).setTitle("需要后台运行权限")
                .setMessage("远程桌面期间 ORH 需要在后台保持连接。未授权时系统可能在一分钟后断开。\n\n请允许“忽略电池优化”，并在厂商设置里放行后台运行/高耗电。")
                .setNegativeButton("继续",(dialog,which) -> openDesktop(address))
                .setPositiveButton("去授权",(dialog,which) -> requestBackground(address)).show();
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
                boolean exempt = getSystemService(PowerManager.class).isIgnoringBatteryOptimizations(getPackageName());
                String bucket = "—";
                if (Build.VERSION.SDK_INT >= 28) bucket = String.valueOf(getSystemService(UsageStatsManager.class).getAppStandbyBucket());
                report.append("后台 ").append(exempt?"已豁免":"未豁免").append(" · 待机分组 ").append(bucket).append("\n");
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
