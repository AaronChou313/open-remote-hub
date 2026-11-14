"""Small public identity endpoint and authenticated portal pairing metadata."""
import json
import os
import platform
import threading
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

PORTAL = 'https://aaronchou313.github.io/open-remote-hub/'
PATH = '/.well-known/openremotehub'
lock = threading.Lock()
router = APIRouter()


def allowed_origin(origin):
    origins = os.environ.get('ORH_DISCOVERY_ORIGINS', 'https://aaronchou313.github.io')
    return origin in {value.strip() for value in origins.split(',') if value.strip()}


def identity():
    from app.main import DATA
    path = DATA / 'instance-id'
    with lock:
        if path.exists():
            identifier = str(uuid.UUID(path.read_text().strip()))
        else:
            identifier = str(uuid.uuid4())
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(identifier)
    return dict(service='openremotehub', protocol=1, instance_id=identifier,
                name=os.environ.get('ORH_INSTANCE_NAME') or platform.node())


@router.api_route(PATH, methods=['GET', 'HEAD', 'OPTIONS'])
def discover(request: Request):
    response = Response(status_code=204) if request.method == 'OPTIONS' else JSONResponse(identity())
    origin = request.headers.get('origin')
    if origin and allowed_origin(origin):
        response.headers.update({'Access-Control-Allow-Origin': origin,
                                 'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS', 'Vary': 'Origin'})
    return response


@router.get('/api/discovery')
def pairing(request: Request):
    from app.main import NETWORK, PORT
    value = identity()
    urls = [str(request.base_url).rstrip('/')]
    if NETWORK.bind not in ('127.0.0.1', '::1', 'localhost'):
        for host in sorted(NETWORK.hosts):
            if host in ('localhost', '127.0.0.1', '::1'):
                continue
            authority = f'[{host}]' if ':' in host else host
            url = f'{request.url.scheme}://{authority}:{PORT}'
            if url not in urls:
                urls.append(url)
    if len(urls) > 1:
        urls = [url for url in urls if url not in (f'{request.url.scheme}://127.0.0.1:{PORT}', f'{request.url.scheme}://localhost:{PORT}', f'{request.url.scheme}://[::1]:{PORT}')]
    # A fragment stays in the browser. It isn't sent to the Pages hosting server.
    payload = dict(name=value['name'], instanceId=value['instance_id'], urls=urls)
    return dict(**value, urls=urls, portal_url=PORTAL + '#add=' + quote(json.dumps(payload, ensure_ascii=False), safe=''))
