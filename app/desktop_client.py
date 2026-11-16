"""Native Client window. The Agent is owned by its existing service process."""
from pathlib import Path
import json
from urllib.parse import urlsplit


def run(url, storage_path):
    import webview
    from webview.menu import Menu, MenuAction

    webview.settings['ALLOW_DOWNLOADS'] = True
    client_origin = urlsplit(url)

    def open_terminal(target):
        address = urlsplit(target)
        source = urlsplit(window.get_current_url() or '')
        host = address.hostname or ''
        local_agent = (address.scheme, address.netloc) == (client_origin.scheme, client_origin.netloc)
        if (address.scheme not in ('http', 'https') or address.username or address.password
                or not (local_agent or host in ('127.0.0.1', 'localhost', '::1') or host.endswith('.localhost'))
                or not address.path.startswith('/terminal/open/')):
            raise ValueError('终端入口必须来自本机 Client 网关')
        if (source.scheme, source.netloc) != (address.scheme, address.netloc):
            raise ValueError('请从当前设备工作区打开终端')
        webview.create_window('OpenRemoteHub · 终端', target, width=1100, height=760,
                              min_size=(600, 400))

    Path(storage_path).mkdir(parents=True, exist_ok=True, mode=0o700)
    window = webview.create_window('OpenRemoteHub', url, width=1280, height=840,
                                   min_size=(680, 480))

    def terminal_request(event, key, value):
        if event != 'change' or key != 'terminal_request':
            return
        try:
            if not isinstance(value, dict) or not isinstance(value.get('url'), str):
                raise ValueError('终端入口无效')
            open_terminal(value['url'])
        except ValueError as error:
            window.state.terminal_error = str(error)

    # Shared state uses the native bridge without eval-based API generation,
    # so Agent pages retain their existing script-src CSP.
    window.state += terminal_request

    def close_terminals():
        for child in list(webview.windows):
            if child is not window:
                child.destroy()

    window.events.closed += close_terminals
    def devices():
        window.run_js('if (window.ORHClientWorkspace) { window.ORHClientWorkspace.returnToDevices(); } '
                      'else { window.location.assign(' + json.dumps(url) + '); }')

    menu = [Menu('OpenRemoteHub', [MenuAction('我的设备', devices),
                                  MenuAction('关闭窗口', window.destroy)])]
    webview.start(private_mode=False, storage_path=str(storage_path), menu=menu)
