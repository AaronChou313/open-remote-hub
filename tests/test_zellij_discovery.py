import sys,time,json
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


def test_renamed_session_keeps_verified_process_identity(tmp_path,monkeypatch):
    root=tmp_path/'cache'
    folder=root/'contract_version_1/session_info/renamed'
    folder.mkdir(parents=True)
    (folder/'session-layout.kdl').write_text('layout {}')
    marker=folder/'orh-process.json'
    marker.write_text(json.dumps({'pid':3456,'created':123.0}))
    sockets=tmp_path/'sockets';sockets.mkdir();(sockets/'renamed').touch()
    class Process:
        pid=3456
        info={'name':'zellij','cmdline':['zellij','--server',str(sockets/'original')],'uids':None,'status':'running'}
        def create_time(self):return 123.0
        def children(self,recursive=False):return []
    monkeypatch.setattr(discovery,'cache_roots',lambda:[root])
    monkeypatch.setattr(discovery.psutil,'process_iter',lambda attrs:iter([Process()]))
    rows=discovery.host_sessions()
    assert len(rows)==1 and rows[0]['name']=='renamed'
    assert rows[0]['status']=='running' and rows[0]['pid']==3456
    marker.write_text(json.dumps({'pid':3456,'created':122.0}))
    renamed=next(s for s in discovery.host_sessions() if s['name']=='renamed')
    assert renamed['status']=='exited','Stale rename metadata never claims a reused PID'
