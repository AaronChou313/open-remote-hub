import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app import zellij_sessions as discovery


def test_cli_discovery_has_bounded_timeout(monkeypatch):
    def stalled(args, timeout):
        assert args==['zellij','list-sessions','-n']
        assert timeout==2
        raise RuntimeError('timed out')
    monkeypatch.setattr(discovery,'command',stalled)
    monkeypatch.setattr(discovery,'host_sessions',lambda:[{'name':'owned','status':'running','detail':'process evidence'}])
    rows,warning=discovery.discover()
    assert rows[0]['name']=='owned' and warning and '交互正常' in warning


def test_cli_truth_preserved_when_available(monkeypatch):
    monkeypatch.setattr(discovery,'command',lambda args,timeout:'live [Created 1s ago]\nold [Created 1h ago] (EXITED - attach to resurrect)\n')
    rows,warning=discovery.discover()
    assert [(r['name'],r['status']) for r in rows]==[('live','running'),('old','exited')]
    assert warning is None


def test_saved_layout_is_evidence_but_orphan_metadata_is_not(tmp_path,monkeypatch):
    monkeypatch.setattr(discovery.Path,'home',lambda:tmp_path)
    monkeypatch.setattr(discovery.psutil,'process_iter',lambda attrs:iter([]))
    root=tmp_path/'Library/Caches/org.Zellij-Contributors.Zellij/contract_version_1/session_info'
    (root/'saved').mkdir(parents=True)
    (root/'saved/session-layout.kdl').write_text('layout {}')
    (root/'orphan').mkdir()
    (root/'orphan/session-metadata.kdl').write_text('old record')
    assert [(r['name'],r['status']) for r in discovery.host_sessions()]==[('saved','exited')]
