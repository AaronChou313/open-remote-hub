"""Create an update-compatible signed Android installer."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    private = ROOT / '.runtime'
    private.mkdir(mode=0o700, exist_ok=True)
    environment = dict(os.environ)
    if not environment.get('ORH_ANDROID_KEYSTORE'):
        if environment.get('CI') == 'true':
            raise SystemExit('Android release signing key is required in CI')
        key = private / 'android-release.jks'
        config = private / 'android-signing.json'
        if not config.exists():
            config.write_text(json.dumps({'password':secrets.token_urlsafe(32)}))
            config.chmod(0o600)
        environment['ORH_ANDROID_KEYSTORE'] = str(key)
        environment['ORH_ANDROID_PASSWORD'] = json.loads(config.read_text())['password']
        if not key.exists():
            subprocess.run(['keytool','-genkeypair','-keystore',str(key),'-alias','openremotehub','-keyalg','RSA','-keysize','2048','-validity','10000','-dname','CN=OpenRemoteHub','-storepass:env','ORH_ANDROID_PASSWORD','-keypass:env','ORH_ANDROID_PASSWORD'], env=environment, check=True)
            key.chmod(0o600)
    environment['ORH_ANDROID_RELEASE'] = '1'
    subprocess.run(['sh','mesh/packaging/build-android.sh'], cwd=ROOT, env=environment, check=True)
    version = (ROOT/'VERSION').read_text().strip()
    target = ROOT/'dist'/f'OpenRemoteHub-{version}-android-arm64.apk'
    shutil.copy2(ROOT/'client/android/app/build/outputs/apk/release/app-release.apk', target)
    print(target)


if __name__ == '__main__':
    main()
