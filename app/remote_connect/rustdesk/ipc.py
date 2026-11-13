"""RustDesk 1.5.3 local IPC, using upstream serde Data and BytesCodec frames.

Sources and pinned hbb_common revision are listed in README.md. This is a
local client configuration adapter, separate from the remote desktop protocol.
"""
import json
import socket
import stat
from .settings import SOCKET


class NativeError(RuntimeError):
    pass


def frame(message):
    payload = json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode()
    length = len(payload)
    width = next(width for width in range(1, 5) if length < 1 << (width * 8 - 2))
    return ((length << 2) | (width - 1)).to_bytes(width, 'little') + payload


def read_exact(stream, length):
    data = bytearray()
    while len(data) < length:
        part = stream.recv(length - len(data))
        if not part:
            raise NativeError('RustDesk 本机接口已断开，请刷新状态')
        data.extend(part)
    return bytes(data)


def receive(stream):
    first = read_exact(stream, 1)
    width = (first[0] & 3) + 1
    header = first + read_exact(stream, width - 1)
    length = int.from_bytes(header, 'little') >> 2
    if length > 1024 * 1024:
        raise NativeError('RustDesk 本机接口返回异常数据')
    return json.loads(read_exact(stream, length))


class Native:
    def __init__(self, path=SOCKET):
        self.path = path

    def request(self, kind, content=None):
        try:
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode):
                raise NativeError('RustDesk 本机接口不可用')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(3)
                stream.connect(str(self.path))
                stream.sendall(frame({'t': kind, 'c': content}))
                response = receive(stream)
            if response.get('t') == 'SecurityConfigError':
                raise NativeError('RustDesk 拒绝了这项设置，请在原生客户端检查安全策略')
            if response.get('t') != kind:
                raise NativeError('RustDesk 接口版本不兼容，请检查客户端版本')
            return response.get('c')
        except (OSError, ValueError, IndexError) as error:
            raise NativeError('无法连接 RustDesk 本机接口，请启动客户端后重试') from error

    def config(self, name):
        response = self.request('Config', [name, None])
        if not isinstance(response, list) or len(response) != 2 or response[0] != name:
            raise NativeError('RustDesk 配置响应格式异常')
        return response[1]

    def options(self):
        value = self.request('Options')
        if not isinstance(value, dict):
            raise NativeError('RustDesk 设置读取失败，本次未保存')
        return value

    def set_options(self, options):
        if self.request('Options', options) is not None:
            raise NativeError('RustDesk 未确认设置更新，请刷新核对')

    def set_password(self, password):
        response = self.request('Config', ['permanent-password', password])
        if response != ['permanent-password', 'Y']:
            raise NativeError('RustDesk 未接受密码更新，请在原生客户端检查安全策略')


native = Native()
