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
7. **Modbus RTU**：新增 Modbus 标签页，基于现有串口连接支持 `01/02/03/04/05/06/15/16` 功能码，可直接构帧、发送、解析响应，也可一键填入发送区作二次编辑。
8. **MBP 文件**：支持直接打开 Modbus Poll 样例 `mbp/夹爪.mbp`，恢复从站、功能码、起始地址、数量、扫描周期、中文名称及保存值；也支持保存/打开本工具的 JSON `.mbp` 配置。
9. **界面皮肤**：浅色 / 深色 皮肤切换，Fusion 风格 + 自定义 QSS。
10. **配置文件**：默认为程序同目录的 `serial_tool.ini`（便携化）；若程序所在目录不可写，会自动回退到用户目录（Linux/macOS: `~/.config/qt5com/`，Windows: `%APPDATA%\qt5com\`）。自动保存端口参数、显示选项、历史发送、自动回复规则、快捷按钮、Modbus 表单、窗口布局等；**历史发送** 可从下拉框快速调出。

---

## 🚀 快速开始

### 源码运行
```bash
pip install -r requirements.txt
python3 serial_tool.py
```

### Modbus 使用
- 打开串口后切到 `Modbus` 标签页，选择从站、功能码、地址与数量/写入值。
- `读取一次` / `写入一次` 会直接经当前串口发送 Modbus RTU 帧并解析响应。
- `填入发送区` 会把当前配置转成 HEX 帧，便于继续手工调整。
- `打开 MBP…` 支持两类文件：
  - 本工具保存的 JSON `.mbp`：完整恢复 Modbus 配置。
  - Modbus Poll 二进制 `.mbp`：已验证样例使用的 `0x2454 / 0xA8` 布局，未知版本或损坏文件会提示导入失败。
- 夹爪样例导入后为从站 `1`、功能码 `03`、起始地址 `4000 (0x0FA0)`、数量 `32`、扫描周期 `1000 ms`，按截图分两组显示名称和数值。文件中的值是保存时的快照，读取成功后由设备响应刷新。
- 勾选“有符号16位”时，`65535 (0xFFFF)` 显示为 `-1`；写入表单使用原始无符号值 `0~65535`。
- 打开串口后可勾选“自动读取”，按扫描周期读取；等待响应期间不重发，超时提示后继续下一轮，关闭串口自动停止。串口端口、波特率、校验位仍需按设备设置。
- 双击保持寄存器/线圈表格项可填入单个写入表单，修改值后点击“写入一次”发送。
- “填入发送区”仅生成帧，不会发送；打开和保存配置也不会写入设备。
- 保存为本工具 JSON `.mbp` 时保留名称、保存值、扫描周期及显示选项；该 JSON 格式不用于 Modbus Poll 回读，原始二进制样例不受影响。

回归测试：`python3 -m unittest discover -s tests -v`（含无显示环境下的 Qt 界面测试）。

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
