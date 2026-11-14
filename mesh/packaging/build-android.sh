#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
: "${ANDROID_HOME:?Set ANDROID_HOME to the Android SDK directory}"
: "${ANDROID_NDK_HOME:=$ANDROID_HOME/ndk/28.2.13676358}"
export ANDROID_NDK_HOME
mobile_version=v0.0.0-20261011034528-197770444867
go install "golang.org/x/mobile/cmd/gomobile@$mobile_version"
go install "golang.org/x/mobile/cmd/gobind@$mobile_version"
PATH="$(go env GOPATH)/bin:$PATH"
export PATH
mkdir -p client/android/app/libs client/android/app/src/main/assets dist
python3 mesh/packaging/notices.py
cp dist/THIRD_PARTY_NOTICES.txt client/android/app/src/main/assets/THIRD_PARTY_NOTICES.txt
(cd mesh && gomobile bind -target=android/arm64 -androidapi=26 -trimpath -ldflags='-s -w' -javapkg=top.openremotehub.client.core -o ../client/android/app/libs/orh-client.aar ./mobile)
(cd client/android && ./gradlew --no-daemon clean assembleDebug assembleDebugAndroidTest lintDebug)
cp client/android/app/build/outputs/apk/debug/app-debug.apk dist/orh-client-android-debug.apk
