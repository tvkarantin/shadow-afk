#!/bin/sh
set -eu
cd "$(dirname "$0")"
docker_cli=$(command -v docker || true)
if [ -z "$docker_cli" ] && [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
    docker_cli=/Applications/Docker.app/Contents/Resources/bin/docker
fi
: "${docker_cli:?Docker CLI is required}"
"$docker_cli" build --platform linux/amd64 -f Dockerfile.windows -t shadowafk-windows-builder .
mkdir -p release
"$docker_cli" run --rm --platform linux/amd64 \
    --mount "type=bind,src=$PWD,dst=/source,readonly" \
    --mount "type=bind,src=$PWD/release,dst=/output" \
    shadowafk-windows-builder xvfb-run -a sh -ec '
        cp -R /source/shadowafk /source/tests /source/run.py /source/pytest.ini /source/requirements*.txt /source/build.bat /source/installer.iss .
        export BUILD_PYTHON="Z:\opt\python\python.exe"
        export ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        export QT_QUICK_BACKEND=software
        wine cmd /c build.bat
        wine release/ShadowAFK_Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=C:\\ShadowAFK-Test
        wine "C:\ShadowAFK-Test\ShadowAFK.exe" --smoke
        wine "C:\ShadowAFK-Test\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
        (cd dist && zip -q -r /output/ShadowAFK_Portable.zip ShadowAFK)
        cp release/ShadowAFK_Setup.exe /output/
    '
