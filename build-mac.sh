#!/usr/bin/env bash
# macOS 一键打包：固定输出目录，生成 dmg 后提示清理中间产物，避免反复构建堆积磁盘。
set -euo pipefail
cd "$(dirname "$0")"

DIST="dist-mac"
BUILD="build-mac"
DMG="StreamGuard-macOS-arm64.dmg"

echo "[1/3] 打包应用..."
python3 -m PyInstaller stream-guard-mac.spec --noconfirm \
  --distpath "$DIST" --workpath "$BUILD" >/tmp/sg-build.log 2>&1 || {
    tail -20 /tmp/sg-build.log; exit 1;
  }

echo "[2/3] 生成 dmg..."
rm -f "$DMG"
hdiutil create -volname "Stream Guard" -srcfolder "$DIST/Stream Guard.app" \
  -ov -format UDZO "$DMG" >/dev/null 2>&1

echo "[3/3] 完成: $DMG ($(du -sh "$DMG" | cut -f1))"
echo ""
echo "上传: gh release upload <tag> $DMG --clobber"
echo ""
echo "中间产物 $DIST/ 和 $BUILD/ 可删除以释放约 130MB 磁盘："
echo "  rm -rf \"$DIST\" \"$BUILD\""
