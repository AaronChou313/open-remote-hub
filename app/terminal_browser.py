"""Browser compatibility for the installed Zellij client and remote attachments."""
import base64
import asyncio
import contextlib
import hashlib
import os
import re
import secrets
from fastapi import APIRouter, HTTPException, Request
from app import access, file_access as fs

router=APIRouter(prefix='/api/terminal',tags=['terminal'])
IMAGE_LIMIT=20*1024**2


def mobile_client(source):
    """Replace only the known password-based mobile capture in Zellij 0.45.1."""
    start='function installSoftKeyboardCapture(term, sendFunction) {'
    end='// inputmode="none" stops the OS keyboard'
    enabled='window.__zjSoftKbdEnabled = true;'
    if source.count(start)!=1 or source.count(end)!=1 or source.count(enabled)!=1:
        return source,False
    before,remaining=source.split(start,1)
    capture,after=remaining.split(end,1)
    if 'div.type = "password";' not in capture:return source,False
    replacement='function installSoftKeyboardCapture(term, sendFunction) {\n    window.RemoteHubTerminal.installMobileInput(term, sendFunction);\n}\n\n'
    return (before+replacement+end+after).replace(enabled,'window.__zjSoftKbdEnabled = false;',1),True


def client_asset(content):
    source,compatible=mobile_client(content.decode('utf-8'))
    return source.encode('utf-8'),compatible


def client_page(content,asset):
    patched,compatible=client_asset(asset)
    digest=base64.b64encode(hashlib.sha384(patched).digest()).decode()
    html=content.decode('utf-8')
    pattern=r'(<script\b[^>]*\bsrc="assets/app\.js"[^>]*\bintegrity=")[^"]+("[^>]*>)'
    html,count=re.subn(pattern,lambda m:m[1]+'sha384-'+digest+m[2],html)
    if count!=1:raise HTTPException(503,'Zellij Web Client 的页面结构已变化，请检查终端兼容层')
    addon='<link rel="stylesheet" href="/static/terminal-browser.css"><script src="/static/terminal-browser.js" data-mobile-compatible="'+str(compatible).lower()+'"></script>'
    return html.replace('<script type="module" src="assets/app.js"',addon+'<script type="module" src="assets/app.js"',1).encode()


@router.post('/{name}/attachments')
async def image_attachment(name:str,request:Request):
    from app import main
    access.admin(request)
    main.zname(name)
    sessions=main.zellij_list()['sessions']
    if not any(s['name']==name and s['status']=='running' for s in sessions):raise HTTPException(409,'终端会话未运行，请重新连接后上传')
    types={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}
    mime=request.headers.get('content-type','').split(';')[0]
    if mime not in types:raise HTTPException(415,'图片支持 PNG、JPEG 和 WebP')
    length=request.headers.get('content-length')
    if length and (not length.isdecimal() or int(length)>IMAGE_LIMIT):raise HTTPException(413,'终端图片上限为 20 MiB')
    folder=main.DATA/'terminal-attachments'
    folder.mkdir(mode=0o700,exist_ok=True)
    temp='.upload-'+secrets.token_hex(16)
    filename=secrets.token_hex(16)+types[mime]
    total=0;prefix=bytearray()
    fd=os.open(folder,fs.DIR)
    try:
        child=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(child,'wb') as target:
                async for chunk in request.stream():
                    total+=len(chunk)
                    if total>IMAGE_LIMIT:raise HTTPException(413,'终端图片上限为 20 MiB')
                    prefix.extend(chunk[:max(0,12-len(prefix))])
                    await asyncio.to_thread(target.write,chunk)
                await asyncio.to_thread(target.flush)
                await asyncio.to_thread(os.fsync,target.fileno())
            valid=(mime=='image/png' and prefix.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and prefix.startswith(b'\xff\xd8\xff')) or (mime=='image/webp' and prefix[:4]==b'RIFF' and prefix[8:12]==b'WEBP')
            if not valid:raise HTTPException(415,'图片内容与格式不符，请选择有效图片')
            fs.rename_exclusive(fd,temp,fd,filename)
        finally:
            with contextlib.suppress(FileNotFoundError):os.unlink(temp,dir_fd=fd)
    finally:os.close(fd)
    main.audit('terminal-attachment',name,'upload')
    return dict(path=str(folder/filename),size=total)
