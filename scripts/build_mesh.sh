#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p dist
for target in darwin-arm64 linux-amd64 windows-amd64; do
  system=${target%-*}
  architecture=${target#*-}
  extension=""
  if [ "$system" = windows ]; then extension=.exe; fi
  (cd mesh && CGO_ENABLED=0 GOOS="$system" GOARCH="$architecture" go build -trimpath -ldflags='-s -w' -o "../dist/orh-mesh-$target$extension" ./cmd/orh-mesh)
done
echo "built: $(ls dist/orh-mesh-* | tr '\n' ' ')"
