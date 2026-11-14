"""Build the dependency-free Pages entry without including host configuration."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent.parent
output = root / '.runtime' / 'portal-site'
if output.exists():
    shutil.rmtree(output)
output.mkdir(parents=True)
for name in ('index.html', 'portal.css', 'portal.js', 'hosts.mjs', 'favicon.svg', 'cloud.js', 'cloud-config.json'):
    shutil.copyfile(root / 'portal' / name, output / name)
for source, target in [('icons.svg', 'icons.svg'), ('icons-LICENSE.txt', 'icons-LICENSE.txt')]:
    shutil.copyfile(root / 'static' / source, output / target)
(output / '.nojekyll').touch()
print(output)
