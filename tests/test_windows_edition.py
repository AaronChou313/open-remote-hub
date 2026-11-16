from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, platforms, windows_compat


def test_windows_shim_is_a_noop_elsewhere():
    assert windows_compat.install() is False


def test_windows_host_reports_system_and_proxy():
    host = platforms.WindowsHost()
    info = host.info()
    assert info['system'] == 'Windows' and info['cores']
    assert host.proxy_status()['platform'] == 'Windows'
    assert isinstance(host.services(), list)


def test_windows_host_services_tolerate_missing_psutil_api(monkeypatch):
    monkeypatch.delattr(platforms.psutil, 'win_service_iter', raising=False)
    assert platforms.WindowsHost().services() == []


def test_windows_index_exposes_module_management(monkeypatch):
    monkeypatch.setattr(main, 'WINDOWS_EDITION', True)
    page = main.index().body.decode()
    assert 'data-view="modules"' in page
    assert '[data-view="zellij"]{display:none}' not in page
    assert 'id="content"' in page


def test_normal_index_is_untouched(monkeypatch):
    monkeypatch.setattr(main, 'WINDOWS_EDITION', False)
    page = main.index().body.decode()
    assert 'data-view="zellij"' in page
    assert '[data-view="zellij"]{display:none}' not in page
