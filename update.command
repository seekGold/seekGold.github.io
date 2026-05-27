#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"
python3 generate_site_index.py

echo ""
echo "site-index.js 已更新"
echo "按任意键关闭窗口"
read -n 1 -s
