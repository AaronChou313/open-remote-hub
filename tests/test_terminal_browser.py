import base64
import hashlib
from pathlib import Path
from test_files import workspace
from app import main,terminal_browser as browser
from fastapi import HTTPException
import pytest

SOURCE=b'''function installSoftKeyboardCapture(term, sendFunction) {
    const div = document.createElement("input");
    div.type = "password";
}
// inputmode="none" stops the OS keyboard from appearing.
function suppressSoftKeyboardOnTouch() {
    window.__zjSoftKbdEnabled = true;
}
function nativeScrolling() { return "unchanged"; }
'''
PAGE=b'''<html><head><script src="assets/addon-clipboard.js" integrity="sha384-original-addon"></script></head><body><script type="module" src="assets/app.js" integrity="sha384-original-client"></script></body></html>'''
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNBUAAAAASUVORK5CYII=')


def test_mobile_client_patch_and_updated_integrity():
    asset,compatible=browser.client_asset(SOURCE)
    assert compatible and b'window.RemoteHubTerminal.installMobileInput(term, sendFunction)' in asset
    assert b'window.__zjSoftKbdEnabled = false;' in asset
    assert b'div.type = "password"' not in asset
    assert b'function nativeScrolling() { return "unchanged"; }' in asset
    page=browser.client_page(PAGE,SOURCE)
    digest=base64.b64encode(hashlib.sha384(asset).digest())
    assert b'sha384-'+digest in page
    assert b'integrity="sha384-original-addon"' in page
    assert page.index(b'terminal-browser.js')<page.index(b'src="assets/app.js"')
    assert b'data-mobile-compatible="true"' in page
    # Unknown future implementations retain their input code and mark the limit.
    future=SOURCE.replace(b'div.type = "password";',b'div.type = "text";')
    assert browser.client_asset(future)==(future,False)
    assert b'data-mobile-compatible="false"' in browser.client_page(PAGE,future)
    with pytest.raises(HTTPException):browser.client_page(b'<html>unknown page</html>',SOURCE)


def test_terminal_image_upload_is_authenticated_bounded_and_private(workspace,monkeypatch):
    c,key,root=workspace
    monkeypatch.setattr(main,'zellij_list',lambda:{'sessions':[{'name':'fixture','status':'running'}]})
    headers={'Content-Type':'image/png'}
    response=c.post('/api/terminal/fixture/attachments',content=PNG,headers=headers)
    assert response.status_code==200,response.text
    result=response.json();path=Path(result['path'])
    assert path.parent==main.DATA/'terminal-attachments'
    assert path.read_bytes()==PNG and path.suffix=='.png'
    assert path.stat().st_mode&0o777==0o600
    assert c.post('/api/terminal/missing/attachments',content=PNG,headers=headers).status_code==409
    assert c.post('/api/terminal/fixture/attachments',content=b'<svg/>',headers={'Content-Type':'image/svg+xml'}).status_code==415
    assert c.post('/api/terminal/fixture/attachments',content=b'not a png',headers=headers).status_code==415
    assert not list(path.parent.glob('.upload-*'))
    monkeypatch.setattr(browser,'IMAGE_LIMIT',10)
    assert c.post('/api/terminal/fixture/attachments',content=PNG,headers=headers).status_code==413
    assert len(list(path.parent.iterdir()))==1
    assert c.post('/api/terminal/fixture/attachments',content=PNG,headers={**headers,'Origin':'https://evil.test'}).status_code==403
    c.post('/api/logout',json={})
    assert c.post('/api/terminal/fixture/attachments',content=PNG,headers=headers).status_code==401


def test_native_page_gets_compat_layer_but_library_assets_are_preserved(workspace,monkeypatch):
    import httpx
    from app.native_terminal import upstream
    c,_,_=workspace
    async def response(method,path,query):
        if path=='/assets/app.js':return httpx.Response(200,content=SOURCE,headers={'content-type':'text/javascript'})
        if path=='/assets/addon-clipboard.js':return httpx.Response(200,content=b'ORIGINAL_LIBRARY_BYTES',headers={'content-type':'text/javascript'})
        return httpx.Response(200,content=PAGE,headers={'content-type':'text/html'})
    monkeypatch.setattr(upstream,'request',response)
    assert b'terminal-browser.js' in c.get('/terminal/fixture').content
    assert b'window.RemoteHubTerminal.installMobileInput' in c.get('/terminal/assets/app.js').content
    assert c.get('/terminal/assets/addon-clipboard.js').content==b'ORIGINAL_LIBRARY_BYTES'
