package top.openremotehub.client;

import android.app.Activity;
import android.content.*;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
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
    private LinearLayout error;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        url = getIntent().getStringExtra("url");
        peer = getIntent().getStringExtra("peer_ip");
        String name = getIntent().getStringExtra("name");
        Diagnostics.attach(this);
        Diagnostics.log("console", "打开控制台 " + (name == null ? "" : name));
        if (url == null || url.isEmpty()) {
            finish();
            return;
        }
        build(name == null ? "控制台" : name);
        web.loadUrl(url);
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
        bar.addView(iconButton("刷新", () -> reload()));
        bar.addView(iconButton("浏览器", () -> openExternally()));
        root.addView(bar);

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
        web.setWebChromeClient(new WebChromeClient());
        web.setBackgroundColor(getColor(R.color.surface));
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                if (isLocal(target)) return false;
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
                if (error != null) error.setVisibility(View.GONE);
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

    private void reload() {
        if (peer == null || peer.isEmpty()) {
            error.setVisibility(View.GONE);
            web.loadUrl(url);
            return;
        }
        // A restarted core allocates a new port, so ask for a fresh URL.
        new Thread(() -> {
            try {
                JSONObject result = (JSONObject) LocalApi.call("/console", new JSONObject().put("peer_ip", peer), "POST");
                String next = result.optString("url");
                if (next.isEmpty()) throw new Exception("未返回控制台地址");
                url = next;
                runOnUiThread(() -> {
                    error.setVisibility(View.GONE);
                    web.loadUrl(url);
                    Diagnostics.log("console", "控制台已重新建立 " + url);
                });
            } catch (Exception failure) {
                runOnUiThread(() -> fail("重新连接失败：" + failure.getMessage()));
            }
        }, "mesh-console").start();
    }

    private void openExternally() {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (ActivityNotFoundException error) {
            toast("此设备没有可用的浏览器");
        }
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        Diagnostics.log("console", "关闭控制台");
        if (web != null) {
            web.setWebChromeClient(null);
            web.setWebViewClient(null);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
