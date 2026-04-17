#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# Serial Debug Tool 安装/卸载脚本 (Linux)
# 安装路径: /opt/qt5com
# 桌面入口: /usr/share/applications/qt5com.desktop
# 启动命令: qt5com
#
# 用法:
#   sudo ./install.sh            # 安装
#   sudo ./install.sh --uninstall # 卸载
#
set -e

APP_NAME="Serial Debug Tool"
APP_ID="qt5com"
INSTALL_DIR="/opt/qt5com"
BIN_LINK="/usr/local/bin/qt5com"
DESKTOP_FILE="/usr/share/applications/qt5com.desktop"
ICON_DEST="/usr/share/pixmaps/qt5com.png"

HERE="$(cd "$(dirname "$0")" && pwd)"

need_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "✘ 请使用 sudo 运行: sudo $0 $*"
        exit 1
    fi
}

uninstall() {
    need_root "$@"
    echo ">>> 卸载 $APP_NAME ..."
    rm -rf "$INSTALL_DIR"
    rm -f  "$BIN_LINK" "$DESKTOP_FILE" "$ICON_DEST"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true
    echo "✔ 卸载完成。"
}

install_app() {
    need_root "$@"

    # 1. 定位可执行文件
    EXE=""
    if [[ -n "$1" && -f "$1" ]]; then
        EXE="$1"
    else
        # 自动寻找 dist/SerialDebugTool-*
        CANDIDATE=$(ls -1 "$HERE/dist/"SerialDebugTool-* 2>/dev/null | grep -v '\.exe$' | head -n1 || true)
        if [[ -n "$CANDIDATE" && -f "$CANDIDATE" ]]; then
            EXE="$CANDIDATE"
        fi
    fi
    if [[ -z "$EXE" ]]; then
        echo "✘ 未找到可执行文件。请先 'python3 build.py' 或手动指定:"
        echo "    sudo $0 /path/to/SerialDebugTool"
        exit 1
    fi
    echo ">>> 使用可执行文件: $EXE"

    # 2. 图标
    ICON_SRC=""
    for cand in "$HERE/app.png" "$HERE/icon.png"; do
        [[ -f "$cand" ]] && ICON_SRC="$cand" && break
    done

    # 3. 安装
    echo ">>> 安装到 $INSTALL_DIR ..."
    mkdir -p "$INSTALL_DIR"
    install -m 0755 "$EXE" "$INSTALL_DIR/qt5com"
    if [[ -n "$ICON_SRC" ]]; then
        install -m 0644 "$ICON_SRC" "$INSTALL_DIR/app.png"
        install -m 0644 "$ICON_SRC" "$ICON_DEST"
    fi

    # 4. /usr/local/bin 软链接
    ln -sf "$INSTALL_DIR/qt5com" "$BIN_LINK"

    # 5. 桌面入口
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
GenericName=Serial Debug Tool
Comment=串口调试工具 (PyQt5)
Exec=$INSTALL_DIR/qt5com
Icon=${ICON_DEST:-$INSTALL_DIR/app.png}
Terminal=false
Categories=Development;Utility;Electronics;
Keywords=serial;uart;com;rs232;debug;
StartupNotify=true
EOF
    chmod 0644 "$DESKTOP_FILE"

    # 6. 更新桌面数据库
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true

    # 7. 确保 dialout 组提示
    echo
    echo "✔ 安装完成!"
    echo "   启动:   qt5com  (或在应用菜单中点击 \"$APP_NAME\")"
    echo "   卸载:   sudo $0 --uninstall"
    echo
    echo "Tips: 如果打开串口提示权限不足，请执行:"
    echo "    sudo usermod -aG dialout \$USER   # 然后重新登录"
}

case "${1:-}" in
    -h|--help)
        sed -n '2,12p' "$0"
        ;;
    --uninstall|-u)
        uninstall
        ;;
    *)
        install_app "$@"
        ;;
esac
