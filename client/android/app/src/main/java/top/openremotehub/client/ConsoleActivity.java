package top.openremotehub.client;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.*;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Environment;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import org.json.JSONObject;

/**
 * In-app console. The Go core creates a per-device loopback forward and a
 * browser origin ending in .localhost, so the WebView keeps the console's
 * cookies and WebSocket terminal instead of handing the URL to another app.
 */
public final class ConsoleActivity extends Activity {
    private WebView web;
    private TextView status;
    private Button retry;
    private String url;
    private String peer;
    private String deviceID;
    private String deviceName;
    private boolean connecting;
    private final java.util.concurrent.ExecutorService worker=java.util.concurrent.Executors.newSingleThreadExecutor();
    private LinearLayout error;
    private TextView link;
    private volatile boolean agentReady;
    private ValueCallback<Uri[]> fileCallback;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            new Thread(() -> {
                String route="Mesh 尚未连接";
                try {
                    org.json.JSONArray peers=(org.json.JSONArray)LocalApi.call("/peers",null,"GET");
                    route="链路尚未建立";
                    for(int i=0;i<peers.length();i++) {
                        JSONObject value=peers.getJSONObject(i);
                        org.json.JSONArray ips=value.optJSONArray("ips");
                        if(ips==null) continue;
                        for(int j=0;j<ips.length();j++) if(peer.equals(ips.optString(j))) {
                            route="direct".equals(value.optString("path"))?"P2P 直连":"relay".equals(value.optString("path"))?"DERP 中继":"链路尚未建立";
                        }
                    }
                } catch(Exception unavailable) { route="Mesh 不可达"; }
                final String label=route;
                main.post(() -> {if(!isDestroyed()) link.setText((agentReady?"Agent 已连接":"等待 Agent 响应")+" · "+label);});
            }).start();
            main.postDelayed(this,5000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        url = getIntent().getStringExtra("url");
        peer = getIntent().getStringExtra("peer_ip");
        String name = getIntent().getStringExtra("name");
        deviceName=name==null?"控制台":name;
        deviceID=getIntent().getStringExtra("device_id");
        Diagnostics.attach(this);
        Diagnostics.log("console", "打开控制台 " + (name == null ? "" : name));
        if ((url == null || url.isEmpty()) && (deviceID==null || deviceID.isEmpty())) {
            finish();
            return;
        }
        build(name == null ? "控制台" : name);
        if(url==null || url.isEmpty()) prepare();
        else {web.loadUrl(url);main.post(poll);}
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private void build(String title) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(getColor(R.color.surface));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(16), dp(8), dp(8), dp(8));
        TextView label = new TextView(this);
        label.setText(title);
        label.setTextSize(16);
        label.setTypeface(null, Typeface.BOLD);
        label.setTextColor(getColor(R.color.text));
        label.setSingleLine(true);
        label.setEllipsize(android.text.TextUtils.TruncateAt.END);
        label.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1f));
        bar.addView(label);
        bar.addView(iconButton("我的设备", () -> finish()));
        bar.addView(iconButton("控制台", () -> {if(url!=null)web.loadUrl(Uri.parse(url).buildUpon().path("/").fragment("overview").build().toString());}));
        bar.addView(iconButton("刷新", () -> reload()));
        root.addView(bar);
        link=new TextView(this);
        link.setTextSize(12); link.setTextColor(getColor(R.color.muted));
        link.setPadding(dp(16),0,dp(16),dp(6));
        root.addView(link);

        FrameLayout frame = new FrameLayout(this);
        frame.setLayoutParams(new LinearLayout.LayoutParams(-1, 0, 1f));
        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(false);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new Object() {
            @JavascriptInterface public void returnToDevices() { runOnUiThread(() -> finish()); }
            @JavascriptInterface public void agentReady(boolean ready) { agentReady=ready; }
            @JavascriptInterface public void openService(String address) {
                Uri target = Uri.parse(address);
                boolean webService = ("http".equals(target.getScheme()) || "https".equals(target.getScheme()))
                        && target.getHost() != null && target.getHost().startsWith("app-" + deviceID + "-")
                        && target.getHost().endsWith(".localhost");
                if (!webService && !"rustdesk".equals(target.getScheme())) return;
                runOnUiThread(() -> {
                    Intent service = new Intent(ConsoleActivity.this, MeshService.class).putExtra("desktop", true);
                    startForegroundService(service);
                    try { startActivity(new Intent(Intent.ACTION_VIEW, target)); }
                    catch (ActivityNotFoundException unavailable) { toast("请先安装 RustDesk 或浏览器"); }
                });
            }
            @JavascriptInterface public void openTerminal(String address) {
                Uri target=Uri.parse(address), origin=Uri.parse(url);
                if(isLocal(target)&&origin.getAuthority().equals(target.getAuthority())&&target.getPath()!=null&&target.getPath().startsWith("/terminal/open/")) runOnUiThread(() -> web.loadUrl(address));
            }
        }, "ORHAndroid");
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onConsoleMessage(ConsoleMessage message) {
                if(message.messageLevel()==ConsoleMessage.MessageLevel.ERROR) Diagnostics.log("console-web",message.message());
                return false;
            }
            @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams parameters) {
                if(fileCallback!=null) fileCallback.onReceiveValue(null);
                fileCallback=callback;
                Intent choose=parameters.createIntent();
                try {startActivityForResult(choose,41);return true;}
                catch(ActivityNotFoundException unavailable) {fileCallback=null;return false;}
            }
        });
        web.setDownloadListener((address,userAgent,contentDisposition,mimeType,length) -> {
            if(!isLocal(Uri.parse(address))) {toast("请从设备工作区下载文件");return;}
            String filename=URLUtil.guessFileName(address,contentDisposition,mimeType);
            DownloadManager.Request request=new DownloadManager.Request(Uri.parse(address));
            String cookie=CookieManager.getInstance().getCookie(address);
            if(cookie!=null) request.addRequestHeader("Cookie",cookie);
            request.setTitle(filename).setMimeType(mimeType)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalFilesDir(this,Environment.DIRECTORY_DOWNLOADS,filename);
            getSystemService(DownloadManager.class).enqueue(request);
            toast("已开始下载 "+filename);
        });
        web.setBackgroundColor(getColor(R.color.surface));
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if(url==null)return null;
                Uri address=request.getUrl(), origin=Uri.parse(url);
                if(!"GET".equals(request.getMethod())||!origin.getAuthority().equals(address.getAuthority())) return null;
                String path=address.getPath(), asset;
                if("/".equals(path)) asset="index.html";
                else if("/auth/cloud".equals(path)) asset="cloud-auth.html";
                else if(path!=null&&path.startsWith("/static/")) asset=path.substring(8);
                else return null;
                if(asset.contains("..")) return null;
                String mime=asset.endsWith(".js")?"application/javascript":asset.endsWith(".css")?"text/css":asset.endsWith(".html")?"text/html":asset.endsWith(".svg")?"image/svg+xml":asset.endsWith(".png")?"image/png":"application/octet-stream";
                try {
                    java.util.Map<String,String> headers=new java.util.HashMap<>();
                    headers.put("Cache-Control","no-store");
                    headers.put("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src http://*.localhost:*; connect-src 'self'; base-uri 'none'; form-action 'self'");
                    return new WebResourceResponse(mime,"UTF-8",200,"OK",headers,getAssets().open("workspace/"+asset));
                } catch(java.io.IOException unavailable) { return null; }
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                if (isLocal(target) || isCloud(target)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, target));
                } catch (ActivityNotFoundException error) {
                    toast("此设备没有可用的浏览器");
                }
                return true;
            }

            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError description) {
                if (request.isForMainFrame()) fail("控制台连接中断：" + description.getDescription());
            }

            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 500) fail("控制台暂时不可用（HTTP " + response.getStatusCode() + "）");
            }

            @Override public void onPageFinished(WebView view, String address) {
                if(isLocal(Uri.parse(address))) view.evaluateJavascript("window.open=function(url){ORHAndroid.openTerminal(new URL(url,location.href).href);return {opener:null};};document.querySelectorAll('a[target=_blank]').forEach(function(a){if(a.pathname.indexOf('/terminal/open/')===0)a.removeAttribute('target');});",null);
            }
        });
        web.setLayoutParams(new FrameLayout.LayoutParams(-1, -1));
        frame.addView(web);

        error = new LinearLayout(this);
        error.setOrientation(LinearLayout.VERTICAL);
        error.setGravity(Gravity.CENTER);
        error.setPadding(dp(32), dp(32), dp(32), dp(32));
        error.setVisibility(View.GONE);
        error.setBackgroundColor(getColor(R.color.surface));
        status = new TextView(this);
        status.setTextColor(getColor(R.color.text));
        status.setTextSize(15);
        status.setGravity(Gravity.CENTER);
        error.addView(status);
        retry = new Button(this);
        retry.setText("重新连接");
        retry.setAllCaps(false);
        retry.setOnClickListener(view -> reload());
        error.addView(retry);
        frame.addView(error, new FrameLayout.LayoutParams(-1, -1));

        root.addView(frame);
        setContentView(root);
        // Keep the toolbar clear of status/navigation bars under edge-to-edge.
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            } else {
                view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
    }

    private Button iconButton(String text, Runnable work) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(13);
        button.setOnClickListener(view -> work.run());
        return button;
    }

    private static boolean isCloud(Uri target) {
        String host = target.getHost();
        return host != null && (host.equals("cloud.openremotehub.top") || host.endsWith(".openremotehub.top"));
    }
    private static boolean isLocal(Uri target) {
        String host = target.getHost();
        return host != null && (host.endsWith(".localhost") || host.equals("localhost") || host.equals("127.0.0.1"));
    }

    private void fail(String message) {
        Diagnostics.log("console", message);
        if (error == null) return;
        status.setText(message + "\n\n请返回设备列表重新打开，或检查 ORH / 组网是否在线。");
        error.setVisibility(View.VISIBLE);
    }

    private void prepare() {
        if(connecting) return;
        connecting=true;
        status.setText("正在连接目标 Agent…");error.setVisibility(View.VISIBLE);retry.setVisibility(View.GONE);
        worker.execute(() -> {
            try {
                String address=LocalApi.consoleURL(this,deviceID,peer,deviceName);
                main.post(() -> {
                    if(isDestroyed()||isFinishing()) return;
                    connecting=false;url=address;error.setVisibility(View.GONE);retry.setVisibility(View.VISIBLE);
                    web.loadUrl(url);main.removeCallbacks(poll);main.post(poll);
                });
            } catch(Exception failure) {
                main.post(() -> {if(!isDestroyed()){connecting=false;retry.setVisibility(View.VISIBLE);fail(failure.getMessage());}});
            }
        });
    }

    private void reload() {
        if(deviceID!=null&&!deviceID.isEmpty()){prepare();return;}
        if (peer == null || peer.isEmpty()) {
            error.setVisibility(View.GONE);
            web.loadUrl(url);
            return;
        }
        error.setVisibility(View.GONE);
        web.reload();
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        main.removeCallbacks(poll);
        worker.shutdownNow();
        if(fileCallback!=null) fileCallback.onReceiveValue(null);
        Diagnostics.log("console", "关闭控制台");
        if (web != null) {
            web.setWebChromeClient(null);
            web.setWebViewClient(null);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request==41&&fileCallback!=null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,data));
            fileCallback=null;
        }
    }
}
