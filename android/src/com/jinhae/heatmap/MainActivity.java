package com.jinhae.heatmap;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 마켓 히트맵 셸.
 *
 * 이 앱은 화면을 직접 그리지 않는다. GitHub Pages에 올라간 히트맵을 WebView로 띄운다.
 * 그렇게 한 이유: 유니버스나 시각화를 고칠 때마다 APK를 다시 빌드하고 설치하는 대신,
 * 레포에 푸시만 하면 다음 실행에서 반영되게 하기 위해서다.
 *
 * 앱이 실제로 담당하는 것은 네이티브 셸이 해야만 하는 세 가지뿐이다.
 *   1) 오프라인일 때 빈 흰 화면 대신 재시도 UI를 보여준다
 *   2) 뒤로가기를 WebView 히스토리에 연결한다
 *   3) 앱 복귀 시 시세를 새로 고친다
 */
public class MainActivity extends Activity {

    private static final String URL = "https://jinhae8971.github.io/market-heatmap/";

    private WebView web;
    private LinearLayout offline;
    private boolean loadFailed = false;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0B0D10"));

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0B0D10"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);          // D3 트리맵 렌더링에 필수
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        }

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                // 앱 안에서는 우리 도메인만. 외부 링크는 WebView에 가두지 않는다.
                String u = req.getUrl().toString();
                return !u.startsWith("https://jinhae8971.github.io/");
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req,
                                        android.webkit.WebResourceError err) {
                if (req.isForMainFrame()) {
                    loadFailed = true;
                    showOffline(true);
                }
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                if (!loadFailed) showOffline(false);
            }
        });

        offline = buildOfflineView();
        offline.setVisibility(View.GONE);

        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(offline, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        applyInsets(root);
        setContentView(root);

        load();
    }

    /**
     * targetSdk 35(Android 15)부터는 엣지투엣지가 강제된다.
     * 이 처리를 빼면 히트맵 상단 탭이 상태바 아래로 파고들어 가려진다.
     */
    private void applyInsets(final View root) {
        root.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override
            public android.view.WindowInsets onApplyWindowInsets(
                    View v, android.view.WindowInsets insets) {
                int top, bottom, left, right;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    android.graphics.Insets bars = insets.getInsets(
                            android.view.WindowInsets.Type.systemBars());
                    top = bars.top; bottom = bars.bottom;
                    left = bars.left; right = bars.right;
                } else {
                    top = insets.getSystemWindowInsetTop();
                    bottom = insets.getSystemWindowInsetBottom();
                    left = insets.getSystemWindowInsetLeft();
                    right = insets.getSystemWindowInsetRight();
                }
                v.setPadding(left, top, right, bottom);
                return insets;
            }
        });
    }

    private LinearLayout buildOfflineView() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.parseColor("#0B0D10"));

        TextView msg = new TextView(this);
        msg.setText(R.string.offline);
        msg.setTextColor(Color.parseColor("#8B97A4"));
        msg.setTextSize(14f);
        msg.setGravity(Gravity.CENTER);

        Button retry = new Button(this);
        retry.setText(R.string.retry);
        retry.setTextColor(Color.parseColor("#E8EDF2"));
        retry.setBackgroundColor(Color.parseColor("#14181D"));
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                load();
            }
        });

        box.addView(msg);
        box.addView(retry);
        return box;
    }

    private boolean online() {
        ConnectivityManager cm =
                (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        if (cm == null) return true;
        NetworkInfo ni = cm.getActiveNetworkInfo();
        return ni != null && ni.isConnected();
    }

    private void load() {
        loadFailed = false;
        if (!online()) {
            showOffline(true);
            return;
        }
        showOffline(false);
        web.loadUrl(URL);
    }

    private void showOffline(boolean on) {
        offline.setVisibility(on ? View.VISIBLE : View.GONE);
        web.setVisibility(on ? View.GONE : View.VISIBLE);
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 앱으로 돌아왔을 때 지난 시세를 보여주지 않도록 새로 고친다
        if (!loadFailed && web.getUrl() != null) web.reload();
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
