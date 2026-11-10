#!/usr/bin/env python3
"""Local OS-user-only proxy controls; no console password or subscription in argv."""
import argparse
import http.client
import json
from pathlib import Path
import socket
import sys
import webbrowser

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','start','stop','open'])
    args=parser.parse_args()
    if args.action=='open':webbrowser.open('http://127.0.0.1:8765/#proxy');return
    config=json.loads((ROOT/'.runtime/proxy/connection.json').read_text())
    class UnixHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(50);self.sock.connect(config['socket'])
    def call(method,path,body=None):
        c=UnixHTTP('localhost');c.request(method,path,body=json.dumps(body) if body else None,headers={'Content-Type':'application/json'})
        r=c.getresponse();value=json.loads(r.read());c.close()
        if r.status>=400:raise SystemExit(value.get('detail','Proxy error'))
        return value
    state=call('GET','/orh/state')
    if args.action!='status':state=call('POST','/orh/control',{'action':'enable' if args.action=='start' else 'disable','revision':state['revision']})
    print(json.dumps(state,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
