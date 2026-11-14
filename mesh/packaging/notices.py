from pathlib import Path
import subprocess, json, os, re

root = Path(__file__).resolve().parents[2]
os.chdir(root)
go = "go"
decoder = json.JSONDecoder()
modules = {}
for system in ["darwin", "windows", "linux"]:
    text = subprocess.check_output(
        [go, "list", "-deps", "-json", "./cmd/orh-mesh"],
        env=dict(
            os.environ,
            GOOS=system,
            GOARCH="amd64" if system != "darwin" else "arm64",
            CGO_ENABLED="0",
        ),
        text=True,
    )
    while text.strip():
        item, end = decoder.raw_decode(text.lstrip())
        text = text.lstrip()[end:]
        module = item.get("Module")
        if module and not module.get("Main") and module.get("Dir"):
            modules[module["Path"]] = Path(module["Dir"])
mobile = json.loads(
    subprocess.check_output(
        [go, "list", "-m", "-json", "golang.org/x/mobile"], text=True
    )
)
modules[mobile["Path"]] = Path(mobile["Dir"])
parts = ["Third-party notices for OpenRemoteHub Mesh\n\n"]
parts.append(
    "Go standard library\n"
    + (
        Path(subprocess.check_output([go, "env", "GOROOT"], text=True).strip())
        / "LICENSE"
    ).read_text()
    + "\n\n"
)
for name, folder in sorted(modules.items()):
    files = [
        p
        for p in folder.iterdir()
        if p.is_file()
        and re.match(r"^(LICENSE|LICENCE|COPYING|NOTICE)(\b|[._-])", p.name, re.I)
    ]
    if not files:
        raise RuntimeError("Missing module license " + name)
    for path in files:
        parts.append(
            name + " — " + path.name + "\n" + path.read_text(errors="replace") + "\n\n"
        )
(root / "dist/THIRD_PARTY_NOTICES.txt").write_text("".join(parts))
print("Collected upstream notices for", len(modules), "modules and Go")
