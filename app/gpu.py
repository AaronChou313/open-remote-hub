"""Best-effort GPU information; no privileged calls."""
import json
import shutil
import subprocess
import sys
import time

_cache = (0.0, None)


def info():
    global _cache
    now = time.time()
    if _cache[1] is not None and now - _cache[0] < 60:
        return _cache[1]
    data = None
    try:
        if sys.platform == 'darwin':
            out = subprocess.run(['system_profiler', 'SPDisplaysDataType', '-json'], capture_output=True, text=True, timeout=12).stdout
            chips = json.loads(out).get('SPDisplaysDataType') or []
            if chips:
                chip = chips[0]
                data = {'name': chip.get('sppci_model') or chip.get('_name') or 'GPU',
                        'cores': chip.get('sppci_cores') or None, 'vram': chip.get('spdisplays_vram') or None}
        elif shutil.which('nvidia-smi'):
            out = subprocess.run(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=8).stdout.strip().splitlines()
            if out:
                name, util, used, total = [part.strip() for part in out[0].split(',')]
                data = {'name': name, 'util': float(util), 'memory_used': int(used) * 1024 * 1024, 'memory_total': int(total) * 1024 * 1024}
        elif sys.platform.startswith('linux') and shutil.which('lspci'):
            out = subprocess.run(['lspci'], capture_output=True, text=True, timeout=5).stdout
            line = next((item for item in out.splitlines() if 'VGA' in item or '3D controller' in item), None)
            if line:
                data = {'name': line.split(': ', 1)[-1]}
        elif sys.platform == 'win32':
            script = "(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name)"
            out = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True, timeout=10).stdout.strip()
            if out:
                data = {'name': out}
    except Exception:
        data = None
    _cache = (now, data)
    return data
