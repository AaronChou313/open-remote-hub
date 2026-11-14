from pathlib import Path
import importlib.util
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import orn_runtime

SPEC = importlib.util.spec_from_file_location('orn_setup', Path(__file__).resolve().parents[1] / 'scripts' / 'orn_setup.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_source_never_returns_the_destination(tmp_path, monkeypatch):
    root = tmp_path / 'open-remote-hub'
    (root / 'bin').mkdir(parents=True)
    system, architecture = orn_runtime.target()
    built = tmp_path / 'open-remote-net' / 'dist' / f'orn-agent-{system}-{architecture}'
    built.parent.mkdir(parents=True)
    built.write_text('new-build')
    built.chmod(0o755)
    name = 'orn-agent.exe' if sys.platform == 'win32' else 'orn-agent'
    destination = root / 'bin' / name
    destination.write_text('old-copy')
    monkeypatch.setattr(setup, 'ROOT', root)
    monkeypatch.delenv('ORH_ORN_SOURCE', raising=False)
    assert setup.source_binary(destination) == built
    setup.install_binary(built, destination)
    assert destination.read_text() == 'new-build'
    assert not (root / 'bin' / 'orn-agent.tmp').exists()


def test_install_is_a_noop_when_source_is_destination(tmp_path):
    target = tmp_path / 'orn-agent'
    target.write_text('same')
    assert setup.install_binary(target, target) == target
    assert target.read_text() == 'same'
