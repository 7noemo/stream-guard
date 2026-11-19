#!/usr/bin/env bash
# macOS 一键打包：固定输出目录，生成 dmg 后自动清理中间产物，避免反复构建堆积磁盘。
set -euo pipefail
cd "$(dirname "$0")"

DIST="dist-mac"
BUILD="build-mac"
DMG="StreamGuard-macOS-arm64.dmg"

echo "[1/4] 打包应用..."
python3 -m PyInstaller stream-guard-mac.spec --noconfirm \
  --distpath "$DIST" --workpath "$BUILD" >/tmp/sg-build.log 2>&1 || {
    tail -20 /tmp/sg-build.log; exit 1;
  }

echo "[2/4] 生成 dmg..."
rm -f "$DMG"
hdiutil create -volname "Stream Guard" -srcfolder "$DIST/Stream Guard.app" \
  -ov -format UDZO "$DMG" >/dev/null 2>&1

echo "[3/4] 清理中间构建产物（可安全再生）..."
python3 -c "
import shutil, os
for d in ['$BUILD', '$DIST']:
    if os.path.isdir(d):
        shutil.rmtree(d)
"

echo "[4/4] 完成: $DMG ($(du -sh "$DMG" | cut -f1))"
echo "上传: gh release upload <tag> $DMG --clobber"
