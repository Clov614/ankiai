"""往复习界面 webview 注入选中跟踪脚本。

mouseup / selectionchange 时把选中文本 base64 后经 pycmd 回传 Python 侧缓存。
脚本带 window 标志位防重复安装（整页刷新后标志清空，会重新安装）。
"""

from __future__ import annotations

INSTALL_JS = r"""
(function () {
    if (window.__ankiaiInstalled) { return; }
    window.__ankiaiInstalled = true;
    function currentText() {
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed) { return ""; }
        var t = String(sel.toString());
        return t.length > 20000 ? t.slice(0, 20000) : t;
    }
    function send() {
        try {
            var t = currentText();
            var b64 = btoa(unescape(encodeURIComponent(t)));
            pycmd("ankiai:sel:" + b64);
        } catch (e) { /* 忽略：页面未就绪等 */ }
    }
    document.addEventListener("mouseup", send, true);
    document.addEventListener("selectionchange", function () {
        clearTimeout(window.__ankiaiT);
        window.__ankiaiT = setTimeout(send, 250);
    }, true);
})();
"""


def install(webview) -> None:
    try:
        webview.eval(INSTALL_JS)
    except Exception:
        pass  # 页面尚未就绪时 AnkiWebView 会自动排队，此处仅防御异常
