"""SSH operations accept authenticated private-network HTTP and HTTPS."""
import ipaddress
import os

from fastapi import HTTPException

DEFAULT_NETWORKS = '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,::1/128,fc00::/7,fe80::/10'


def require_transport(request):
    if request.url.scheme in ('https', 'wss'):
        return
    try:
        networks = [ipaddress.ip_network(value.strip(), strict=False)
                    for value in os.environ.get('ORH_SSH_HTTP_NETWORKS', DEFAULT_NETWORKS).split(',') if value.strip()]
    except ValueError:
        raise HTTPException(503, 'ORH_SSH_HTTP_NETWORKS 配置无效，请使用逗号分隔的 IP 或 CIDR') from None
    try:
        address = ipaddress.ip_address(request.client.host)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
    except (ValueError, AttributeError):
        raise HTTPException(403, '无法识别 SSH 操作的连接来源') from None
    if any(address in network for network in networks):
        return
    raise HTTPException(403, '此 HTTP 来源未在允许的网络内，请使用 HTTPS 或配置 ORH_SSH_HTTP_NETWORKS')
