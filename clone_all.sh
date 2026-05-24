#!/bin/bash
set -e

BASE="C:/Users/15403/Downloads/github-repos"
cd "$BASE"

REPOS=(
  "https://github.com/matheusvilano/pywwise.git"
  "https://github.com/ak-brodrigue/waapi-python-tools.git"
  "https://github.com/audiokinetic/waapi-client-python.git"
  "https://github.com/audiokinetic/waapi-client.git"
  "https://github.com/BilkentAudio/Wwise-MCP.git"
  "https://github.com/alloc/preact-in-motion.git"
  "https://github.com/zcyh147/Everyone-Can-Use-WAAPI.git"
  "https://github.com/adamtcroft/WaapiCS.git"
  "https://github.com/johnloser-lwi/WwiseTools.git"
  "https://github.com/johnloser-lwi/CustomReascript.git"
  "https://github.com/johnloser-lwi/GA4_Wwise.git"
  "https://github.com/johnloser-lwi/file-watch.git"
  "https://github.com/johnloser-lwi/sound_portfolio.git"
  "https://github.com/decasteljau/waapi-text-to-speech.git"
  "https://github.com/WarppAudio/warpp-audio-waapi-tools.git"
  "https://github.com/WarppAudio/wwise-mikro-scripts.git"
  "https://github.com/ak-brodrigue/waql-playground.git"
  "https://github.com/decasteljau/waapi-import-by-name.git"
  "https://github.com/decasteljau/file-classifier.git"
  "https://github.com/decasteljau/waapi-python-tools-1.git"
  "https://github.com/decasteljau/waapi-offset-property.git"
  "https://github.com/decasteljau/jsfxr-for-wwise.git"
  "https://github.com/decasteljau/waapi-hello-wwise-async.git"
  "https://github.com/octopus-software-team/waapi-laravel.git"
  "https://github.com/aadsache/waapi_tools.git"
)

TOTAL=${#REPOS[@]}
SUCCESS=0
FAILED=0
FAILS=""

echo "=========================================="
echo "  GitHub 仓库批量下载工具"
echo "  总计: $TOTAL 个仓库"
echo "=========================================="
echo ""

for i in "${!REPOS[@]}"; do
  URL="${REPOS[$i]}"
  NAME=$(basename "$URL" .git)
  NUM=$((i + 1))
  
  if [ -d "$BASE/$NAME" ]; then
    echo "[$NUM/$TOTAL] ⏭  跳过 (已存在): $NAME"
    SUCCESS=$((SUCCESS + 1))
    continue
  fi
  
  echo "[$NUM/$TOTAL] 📦 下载: $NAME"
  if git clone --depth=1 "$URL" "$BASE/$NAME" > /dev/null 2>&1; then
    echo "      ✅ 成功"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "      ❌ 失败: $NAME"
    FAILED=$((FAILED + 1))
    FAILS="$FAILS\n  - $NAME"
  fi
  sleep 1
done

echo ""
echo "=========================================="
echo "  下载完成"
echo "  成功: $SUCCESS / $TOTAL"
echo "  失败: $FAILED"
echo "=========================================="

if [ $FAILED -gt 0 ]; then
  echo ""
  echo "失败的仓库:$FAILS"
fi
