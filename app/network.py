"""Explicit destination allowlist shared by HTTP and native WebSockets."""
import ipaddress
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


def hostname(value):
    value = value.strip().lower()
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        if len(value) <= 253 and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) and all(
            0 < len(label) <= 63 and not label.startswith('-') and not label.endswith('-')
            for label in value.split('.')
        ):
            return value
    raise ValueError('ORH_ALLOWED_HOSTS must contain comma-separated IPs or hostnames, without ports, schemes or wildcards')


@dataclass(frozen=True)
class Network:
    bind: str
    hosts: frozenset

    @classmethod
    def load(cls):
        bind = os.environ.get('ORH_HOST', '127.0.0.1').strip()
        if bind != 'localhost':
            try: bind = ipaddress.ip_address(bind).compressed
            except ValueError: raise ValueError('ORH_HOST must be a local IP, 0.0.0.0, :: or localhost') from None
        hosts = {'localhost', '127.0.0.1', '::1'}
        hosts.update(hostname(v) for v in os.environ.get('ORH_ALLOWED_HOSTS', '').split(',') if v.strip())
        if bind not in ('0.0.0.0', '::', 'localhost'):
            hosts.add(bind)
        if hosts.intersection({'0.0.0.0', '::'}):
            raise ValueError('Wildcard bind addresses cannot be used as allowed destination hosts')
        return cls(bind, frozenset(hosts))

    def local_url(self, port):
        address = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(self.bind, self.bind)
        return f'http://{f"[{address}]" if ":" in address else address}:{port}'

    def allows(self, authority, port, scheme='http'):
        try:
            if not authority or any(c in authority for c in '/\\?#@') or any(c.isspace() for c in authority):
                return False
            url = urlsplit(f'{scheme}://{authority}')
            effective_port = url.port if url.port is not None else (443 if scheme == 'https' else 80)
            return url.hostname in self.hosts and effective_port == port and not authority.endswith(':')
        except ValueError:
            return False

    def same_origin(self, authority, origin, port, scheme='http'):
        return self.allows(authority, port, scheme) and origin == f'{scheme}://{authority}'
