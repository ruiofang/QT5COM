# Serial Debug Tool

一个基于 **Python 3 + PyQt5 + pyserial** 的跨平台串口调试工具，单文件即可运行，打包后为便携式可执行程序。

- **版本**：V1.0
- **作者**：RUIO
- **协议**：MIT License

---

## ✨ 功能特性

1. **串口管理**：启动自动扫描一次，`⟳` 按钮手动刷新；完整的 数据位 / 校验位 (None/Even/Odd/Mark/Space) / 停止位 配置。
2. **波特率**：下拉常用值（1200 ~ 921600），也可直接输入自定义数字。
3. **发送能力**：
   - HEX / 文本 发送，可附加 `\r\n`
   - **循环发送**（10 ms ~ 600000 ms 可调）
   - 支持 **附加校验**：`SUM` / `XOR` / `CRC16-Modbus` / `CRC16-CCITT`，可指定参与计算的起止字节（1-based，止=0 表示到末尾）
4. **毫秒级日志**：接收/发送均带 `[HH:MM:SS.mmm]` 时间戳；可勾选“保存日志到文件”，按日期写入 `logs/YYYY-MM-DD.log`。
5. **自动回复**：表格式规则，每条独立启用开关；匹配与发送均可独立选择 HEX 或文本。
6. **快捷按钮**：自定义名称的一键指令按钮，持久保存，每条可独立设置 HEX / 附加换行。
7. **界面皮肤**：浅色 / 深色 皮肤切换，Fusion 风格 + 自定义 QSS。
8. **配置文件**：默认为程序同目录的 `serial_tool.ini`（便携化）；若程序所在目录不可写，会自动回退到用户目录（Linux/macOS: `~/.config/qt5com/`，Windows: `%APPDATA%\qt5com\`）。自动保存端口参数、显示选项、历史发送、自动回复规则、快捷按钮、窗口布局等；**历史发送** 可从下拉框快速调出。

---

## 🚀 快速开始

### 源码运行
```bash
pip install -r requirements.txt
python3 serial_tool.py
```

### Linux 权限
```bash
sudo usermod -aG dialout $USER     # 重新登录生效
```

### 打包为单文件可执行程序
```bash
python3 build.py            # 产物: dist/SerialDebugTool-V1.0[.exe|-linux]
python3 build.py --clean    # 清理构建产物
```
- 打包前会自动调用 `gen_icon.py` 生成 `app.png` / `app.ico`（已存在则跳过）。
- Windows 自动为 EXE 嵌入版本资源（文件属性页可见版本号与作者）。
- Linux / Windows 均输出 `--onefile` 单文件，双击即可运行。

### 安装到系统（Linux）
```bash
sudo ./install.sh                 # 安装到 /opt/qt5com，创建桌面快捷方式
sudo ./install.sh --uninstall     # 卸载
```
安装后：
- 终端命令：`qt5com`
- 应用菜单：`Serial Debug Tool`
- 桌面图标：`/usr/share/pixmaps/qt5com.png`
- 配置文件：
  - 便携模式（程序所在目录可写时）：`<程序目录>/serial_tool.ini`
  - 系统安装（`/opt/qt5com`）默认安装目录已开放可写权限，因此仍为 `/opt/qt5com/serial_tool.ini`
  - 若安装目录不可写，则自动回退到用户目录：
    - Linux/macOS：`~/.config/qt5com/serial_tool.ini`
    - Windows：`%APPDATA%\qt5com\serial_tool.ini`
- `sudo ./install.sh --uninstall` 会同时清理 `/opt/qt5com` 以及各用户下的 `~/.config/qt5com/`

---

## 🎨 自定义图标
```bash
python3 gen_icon.py           # 重新生成 app.png / app.ico
```
如需安装 Pillow 才可生成 `.ico`：`pip install pillow`

---

## 📂 运行期目录结构
```
程序目录/
├── SerialDebugTool(.exe)     # 可执行文件
├── serial_tool.ini           # 便携配置
└── logs/
    └── 2026-04-18.log        # 按日期归档日志
```

## 📝 日志示例
```
2026-04-18 10:30:45.123 TX -> AA 55 01 02
2026-04-18 10:30:45.180 RX <- OK\r\n
2026-04-18 10:30:46.050 TX(auto) -> PONG
```

---

## 📜 License

本项目采用 **MIT License** 开源，详见 [LICENSE](LICENSE)。

```
Copyright (c) 2026 RUIO

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
```

---

## 👤 作者

**RUIO** — 欢迎 Issue / PR 与使用反馈。
