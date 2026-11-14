"""Public accounts and metadata only. Browsers navigate directly to Agents."""
from contextlib import asynccontextmanager
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from cloud.store import database, digest, initialize, new_session, password_hash


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title='OpenRemoteHub Cloud', lifespan=lifespan, docs_url=None, redoc_url=None)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    return JSONResponse({'detail':'输入格式不正确，请核对账号、密码或设备信息'},422)


def origins():
    return [value.strip() for value in os.environ.get('ORH_CLOUD_ORIGINS',
        'https://aaronchou313.github.io,https://cloud.openremotehub.top').split(',') if value.strip()]


app.add_middleware(CORSMiddleware, allow_origins=origins(), allow_methods=['GET','POST','PATCH','DELETE'],
                   allow_headers=['Authorization','Content-Type'], allow_credentials=False)


@app.middleware('http')
async def boundaries(request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in origins() and origin != str(request.base_url).rstrip('/'):
        return JSONResponse({'detail':'不允许此页面来源'}, 403)
    if int(request.headers.get('content-length', '0')) > 65536:
        return JSONResponse({'detail':'请求过大'}, 413)
    response = await call_next(request)
    response.headers.update({'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer',
                             'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'DENY'})
    return response


def rate_limit(request, purpose, limit):
    key = digest(purpose + ':' + request.client.host)
    now = time.time()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM attempts WHERE at < ?', (now - 3600,))
        if db.execute('SELECT count(*) FROM attempts WHERE key=? AND at>?', (key, now - 60)).fetchone()[0] >= limit:
            raise HTTPException(429, '操作过于频繁，请稍后重试')
        db.execute('INSERT INTO attempts VALUES (?,?)', (key, now))


def bearer(request):
    value = request.headers.get('authorization', '')
    if not value.startswith('Bearer ') or len(value) > 256:
        raise HTTPException(401, '请登录')
    return digest(value[7:])


def account(request: Request):
    token_hash = bearer(request)
    with database() as db:
        row = db.execute('SELECT users.id,username,sessions.expires FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.digest=? AND sessions.expires>?', (token_hash,time.time())).fetchone()
    if not row:
        raise HTTPException(401, '登录已失效')
    return dict(row) | {'session_digest':token_hash}


def agent(request: Request):
    with database() as db:
        row = db.execute('SELECT * FROM devices WHERE credential_hash=?', (bearer(request),)).fetchone()
    if not row:
        raise HTTPException(401, '设备已解绑或绑定凭据无效')
    return dict(row)


def normalized_address(value):
    try:
        url = urlsplit(value.strip())
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
            raise ValueError()
        hostname = url.hostname.lower()
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', hostname):
                raise ValueError()
        port = url.port
        authority = f'[{hostname}]' if ':' in hostname else hostname
        if port and port != (443 if url.scheme == 'https' else 80):
            authority += ':' + str(port)
        return url.scheme + '://' + authority
    except (ValueError, AttributeError):
        raise HTTPException(422, '地址需为完整 HTTP/HTTPS 入口，不含路径、账号或密码') from None


def addresses(values):
    return list(dict.fromkeys(normalized_address(value) for value in values))


def effective_addresses(row):
    excluded = set(json.loads(row['excluded_addresses']))
    return list(dict.fromkeys([value for value in json.loads(row['agent_addresses']) if value not in excluded] + json.loads(row['manual_addresses'])))


def public_device(row):
    return dict(instance_id=row['instance_id'], name=row['display_name'] or row['name'],
                agent_name=row['name'], os=row['os'], addresses=effective_addresses(row),
                preferred=row['preferred'], port=row['port'], last_seen=row['last_seen'],
                online=time.time() - row['last_seen'] < 100)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.@+\-]*$')
    password: str = Field(min_length=1, max_length=1024)


@app.get('/api/health')
def health():
    return {'service':'openremotehub-cloud','protocol':1}


@app.post('/api/register')
def register(body: Credentials, request: Request):
    rate_limit(request,'register',10)
    username = body.username.lower()
    salt = secrets.token_hex(32)
    hashed = password_hash(body.password, salt)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():
            raise HTTPException(409,'账号已存在')
        identifier = str(uuid.uuid4())
        db.execute('INSERT INTO users VALUES (?,?,?,?,?)',(identifier,username,salt,hashed,time.time()))
        result = new_session(db, identifier)
    return result | {'user':{'id':identifier,'username':username}}


@app.post('/api/login')
def login(body: Credentials, request: Request):
    rate_limit(request,'login',20)
    with database() as db:
        user = db.execute('SELECT * FROM users WHERE username=?',(body.username.lower(),)).fetchone()
        valid = hmac.compare_digest(password_hash(body.password, user['salt'] if user else '00'*32), user['password_hash'] if user else '00'*32)
        if not user or not valid:
            raise HTTPException(401,'账号或密码错误')
        result = new_session(db, user['id'])
    return result | {'user':{'id':user['id'],'username':user['username']}}


@app.get('/api/me')
def me(user=Depends(account)):
    return {key:user[key] for key in ('id','username','expires')}


@app.post('/api/logout')
def logout(user=Depends(account)):
    with database() as db:
        db.execute('DELETE FROM sessions WHERE digest=?',(user['session_digest'],))
    return {'ok':True}


class Metadata(BaseModel):
    instance_id: uuid.UUID
    name: str = Field(min_length=1,max_length=160)
    os: str = Field(max_length=160)
    addresses: list[str] = Field(max_length=64)
    port: int = Field(ge=1,le=65535)


@app.post('/agent/bindings/start')
def start_binding(body: Metadata, request: Request):
    rate_limit(request,'binding-start',10)
    metadata = body.model_dump(mode='json')
    metadata['addresses'] = addresses(body.addresses)
    credential = secrets.token_urlsafe(32)
    code = secrets.token_hex(4).upper()
    with database() as db:
        db.execute('DELETE FROM bindings WHERE expires<?',(time.time(),))
        db.execute('INSERT INTO bindings VALUES (?,?,?,?,?,?,?)', (digest(code),digest(credential),str(body.instance_id),json.dumps(metadata),time.time()+600,None,'pending'))
    portal = os.environ.get('ORH_CLOUD_PORTAL','https://aaronchou313.github.io/open-remote-hub/').rstrip('/')+'/'
    return dict(device_code=credential, user_code=code[:4]+'-'+code[4:], expires_in=600,
                verification_url=portal+'#bind='+code)


class BindingApproval(BaseModel):
    code: str = Field(max_length=20)


@app.get('/api/bindings/{code}')
def binding_preview(code: str, request: Request, user=Depends(account)):
    rate_limit(request,'binding-preview',30)
    code_hash = digest(code.replace('-','').upper())
    with database() as db:
        row = db.execute("SELECT metadata FROM bindings WHERE code_hash=? AND expires>? AND status='pending'",(code_hash,time.time())).fetchone()
    if not row:
        raise HTTPException(404,'绑定码已失效或已使用')
    return json.loads(row['metadata'])


@app.post('/api/bindings/approve')
def approve_binding(body: BindingApproval, request: Request, user=Depends(account)):
    rate_limit(request,'binding-approve',20)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM bindings WHERE code_hash=? AND expires>? AND status='pending'",(digest(body.code.replace('-','').upper()),time.time())).fetchone()
        if not row:
            raise HTTPException(404,'绑定码已失效或已使用')
        if db.execute('SELECT 1 FROM devices WHERE instance_id=?',(row['instance_id'],)).fetchone():
            raise HTTPException(409,'设备已绑定，请先在原账号中解绑')
        metadata = json.loads(row['metadata'])
        now = time.time()
        db.execute('INSERT INTO devices (instance_id,owner_id,credential_hash,name,os,agent_addresses,port,last_seen,created) VALUES (?,?,?,?,?,?,?,?,?)',
                   (row['instance_id'],user['id'],row['credential_hash'],metadata['name'],metadata['os'],json.dumps(metadata['addresses']),metadata['port'],0,now))
        db.execute("UPDATE bindings SET status='approved',owner_id=?,code_hash=NULL WHERE credential_hash=?", (user['id'],row['credential_hash']))
    return {'ok':True,'instance_id':row['instance_id']}


class Poll(BaseModel):
    device_code: str = Field(min_length=20,max_length=256)


@app.post('/agent/bindings/poll')
def poll_binding(body: Poll):
    with database() as db:
        row = db.execute('SELECT bindings.status,bindings.instance_id,bindings.owner_id,users.username FROM bindings LEFT JOIN users ON users.id=bindings.owner_id WHERE credential_hash=? AND expires>?',(digest(body.device_code),time.time())).fetchone()
    if not row:
        raise HTTPException(410,'绑定请求已过期，请生成新绑定码')
    return dict(row)


@app.post('/agent/heartbeat')
def heartbeat(body: Metadata, device=Depends(agent)):
    if str(body.instance_id) != device['instance_id']:
        raise HTTPException(403,'设备标识不匹配')
    urls = addresses(body.addresses)
    with database() as db:
        db.execute('UPDATE devices SET name=?,os=?,agent_addresses=?,port=?,last_seen=? WHERE instance_id=? AND credential_hash=?',
                   (body.name,body.os,json.dumps(urls),body.port,time.time(),device['instance_id'],device['credential_hash']))
    return {'ok':True,'owner_id':device['owner_id'],'interval':30}


@app.get('/api/devices')
def devices(user=Depends(account)):
    with database() as db:
        rows = db.execute('SELECT * FROM devices WHERE owner_id=? ORDER BY coalesce(display_name,name) COLLATE NOCASE',(user['id'],)).fetchall()
    return [public_device(row) for row in rows]


class DeviceEdit(BaseModel):
    name: str | None = Field(default=None,min_length=1,max_length=160)
    addresses: list[str] | None = Field(default=None,max_length=64)
    preferred: str | None = Field(default=None,max_length=2048)


@app.patch('/api/devices/{identifier}')
def edit_device(identifier: str, body: DeviceEdit, user=Depends(account)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM devices WHERE instance_id=? AND owner_id=?',(identifier,user['id'])).fetchone()
        if not row:
            raise HTTPException(404,'设备不存在')
        urls = effective_addresses(row) if body.addresses is None else addresses(body.addresses)
        if not urls:
            raise HTTPException(422,'请保留至少一个访问地址')
        automatic = json.loads(row['agent_addresses'])
        excluded = (set(json.loads(row['excluded_addresses'])) | (set(automatic)-set(urls))) - set(urls)
        manual = [url for url in urls if url not in automatic]
        preferred = normalized_address(body.preferred) if body.preferred else None
        if preferred and preferred not in urls:
            raise HTTPException(422,'首选地址需在设备地址列表中')
        db.execute('UPDATE devices SET display_name=?,manual_addresses=?,excluded_addresses=?,preferred=? WHERE instance_id=?',
                   (body.name or row['display_name'],json.dumps(manual),json.dumps(list(excluded)),preferred,identifier))
    return {'ok':True}


@app.delete('/api/devices/{identifier}')
def unbind(identifier: str, user=Depends(account)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM devices WHERE instance_id=? AND owner_id=?',(identifier,user['id'])).fetchone():
            raise HTTPException(404,'设备不存在')
        db.execute('DELETE FROM bindings WHERE instance_id=?',(identifier,))
        db.execute('DELETE FROM devices WHERE instance_id=?',(identifier,))
    return {'ok':True}


class TicketRequest(BaseModel):
    address: str = Field(max_length=2048)
    state: str = Field(default='',max_length=128)


@app.post('/api/devices/{identifier}/ticket')
def issue_ticket(identifier: str, body: TicketRequest, user=Depends(account)):
    address = normalized_address(body.address)
    ticket = secrets.token_urlsafe(32)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM devices WHERE instance_id=? AND owner_id=?',(identifier,user['id'])).fetchone()
        if not row:
            raise HTTPException(404,'设备不存在')
        if address not in effective_addresses(row):
            raise HTTPException(422,'请先将该访问地址添加到设备')
        db.execute('DELETE FROM tickets WHERE expires<?',(time.time(),))
        db.execute('INSERT INTO tickets VALUES (?,?,?,?,0,?)',(digest(ticket),identifier,user['session_digest'],time.time()+90,body.state))
    return dict(url=address+'/auth/cloud#'+urlencode({'ticket':ticket,'state':body.state}), expires_in=90)


class Redeem(BaseModel):
    ticket: str = Field(min_length=20,max_length=256)


@app.post('/agent/tickets/redeem')
def redeem_ticket(body: Redeem, device=Depends(agent)):
    now = time.time()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT tickets.*,sessions.user_id,sessions.expires AS session_expires FROM tickets JOIN sessions ON sessions.digest=tickets.session_digest WHERE tickets.digest=? AND tickets.instance_id=? AND tickets.used=0 AND tickets.expires>? AND sessions.expires>?',
                         (digest(body.ticket),device['instance_id'],now,now)).fetchone()
        if not row or row['user_id'] != device['owner_id']:
            raise HTTPException(401,'登录凭据已失效、已使用或不属于此设备')
        db.execute('UPDATE tickets SET used=1 WHERE digest=?',(digest(body.ticket),))
    return dict(owner_id=device['owner_id'],instance_id=device['instance_id'],state=row['state'],
                expires=min(now+43200,row['session_expires']))


web = Path(os.environ.get('ORH_CLOUD_WEB', Path(__file__).resolve().parents[1]/'.runtime/portal-site'))


@app.get('/cloud-config.json')
def web_config():
    return {'url':os.environ.get('ORH_CLOUD_PUBLIC_URL','https://cloud.openremotehub.top')}


@app.get('/')
def index():
    return FileResponse(web/'index.html')


app.mount('/assets', StaticFiles(directory=str(web),check_dir=False), name='assets')


@app.get('/{asset}')
def static_asset(asset: str):
    if asset not in ('portal.js','cloud.js','portal.css','hosts.mjs','icons.svg','favicon.svg','icons-LICENSE.txt'):
        raise HTTPException(404)
    return FileResponse(web/asset)
