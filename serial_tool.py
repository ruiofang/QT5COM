#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serial Debug Tool (PyQt5)
Version: V1.0
Author : RUIO
License: MIT
Features:
  1. 串口刷新
  2. 波特率选择 / 自定义
  3. HEX 发送、校验位 (None/Even/Odd/Mark/Space)
  4. 毫秒级日志，保存日志为 日期.log
  5. 自定义自动回复
  6. 简洁美观界面
  7. 配置文件 (程序同目录 ini) 保存上次设置与历史发送
"""

__version__ = "V1.0"
__author__ = "RUIO"

import os
import sys
import json
import time
import datetime
from pathlib import Path


def app_dir() -> str:
    """返回可执行文件 / 脚本所在目录（兼容 PyInstaller 冻结打包）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    """返回配置文件路径。

    优先使用程序同目录下的 serial_tool.ini（便携模式）。
    若该目录不可写（如安装到 /opt/qt5com 之类的系统目录），
    则回退到用户配置目录：
        Linux/macOS:  ~/.config/qt5com/serial_tool.ini
        Windows:      %APPDATA%/qt5com/serial_tool.ini
    """
    portable = os.path.join(app_dir(), "serial_tool.ini")
    # 同目录已有配置文件且可写 -> 沿用（便携模式）
    try:
        if os.path.isfile(portable) and os.access(portable, os.W_OK):
            return portable
        if not os.path.exists(portable) and os.access(app_dir(), os.W_OK):
            return portable
    except Exception:
        pass

    # 回退到用户目录
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    user_dir = os.path.join(base, "qt5com")
    try:
        os.makedirs(user_dir, exist_ok=True)
    except Exception:
        user_dir = os.path.expanduser("~")
    user_ini = os.path.join(user_dir, "serial_tool.ini")

    # 首次回退时，若程序同目录存在只读的默认配置，则拷贝一份作为初始值
    try:
        if not os.path.isfile(user_ini) and os.path.isfile(portable):
            import shutil
            shutil.copyfile(portable, user_ini)
    except Exception:
        pass
    return user_ini

# ---- 修正中文路径下 Qt 插件路径 ----
try:
    import PyQt5
    _qt_plugin = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
    if os.path.isdir(_qt_plugin):
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH",
                              os.path.join(_qt_plugin, "platforms"))
        os.environ.setdefault("QT_PLUGIN_PATH", _qt_plugin)
except Exception:
    pass

from PyQt5.QtCore import (Qt, QTimer, QThread, pyqtSignal, QSettings,
                          QRegExp, QDateTime)
from PyQt5.QtGui import (QTextCursor, QFont, QIcon, QRegExpValidator,
                         QTextCharFormat, QColor, QPalette)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QTextEdit, QPlainTextEdit, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QSplitter, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QStatusBar, QSpinBox, QTabWidget, QAction,
    QStyleFactory, QToolButton, QSizePolicy, QAbstractItemView,
)

import serial
import serial.tools.list_ports


# ------------------------------------------------------------------ #
#  工具函数
# ------------------------------------------------------------------ #
def hex_str_to_bytes(text: str) -> bytes:
    """将 '01 A2 FF' 或 '01A2FF' 形式的字符串转为 bytes。"""
    clean = "".join(ch for ch in text if ch in "0123456789abcdefABCDEF")
    if len(clean) % 2:
        clean = "0" + clean
    return bytes.fromhex(clean) if clean else b""


def bytes_to_hex_str(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def now_ms() -> str:
    t = datetime.datetime.now()
    return t.strftime("%H:%M:%S.") + f"{t.microsecond // 1000:03d}"


# -------------------- 校验算法 -------------------- #
def calc_sum(data: bytes) -> bytes:
    return bytes([sum(data) & 0xFF])


def calc_xor(data: bytes) -> bytes:
    r = 0
    for b in data:
        r ^= b
    return bytes([r & 0xFF])


def calc_crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    # Modbus: 低字节在前
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def calc_crc16_ccitt(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    # 高字节在前
    return bytes([(crc >> 8) & 0xFF, crc & 0xFF])


CHECKSUM_TYPES = ["无", "SUM (1B)", "XOR (1B)", "CRC16-Modbus", "CRC16-CCITT"]


def apply_checksum(data: bytes, ctype: str, start: int, end: int) -> bytes:
    """追加校验字节。start/end 为 1-based 闭区间，end<=0 表示到末尾。"""
    if ctype == "无" or not data:
        return data
    n = len(data)
    s = max(0, start - 1)
    e = n if end <= 0 else min(n, end)
    if s >= e:
        return data
    seg = data[s:e]
    if ctype.startswith("SUM"):
        chk = calc_sum(seg)
    elif ctype.startswith("XOR"):
        chk = calc_xor(seg)
    elif ctype == "CRC16-Modbus":
        chk = calc_crc16_modbus(seg)
    elif ctype == "CRC16-CCITT":
        chk = calc_crc16_ccitt(seg)
    else:
        chk = b""
    return data + chk


# ------------------------------------------------------------------ #
#  串口读取线程
# ------------------------------------------------------------------ #
class SerialReader(QThread):
    data_received = pyqtSignal(bytes)
    error = pyqtSignal(str)

    def __init__(self, ser: serial.Serial, parent=None):
        super().__init__(parent)
        self.ser = ser
        self._running = True

    def run(self):
        buf = bytearray()
        last_t = time.time()
        while self._running:
            try:
                n = self.ser.in_waiting
                if n:
                    chunk = self.ser.read(n)
                    buf.extend(chunk)
                    last_t = time.time()
                else:
                    # 超过 20ms 没新数据就打包发出
                    if buf and (time.time() - last_t) * 1000 > 20:
                        self.data_received.emit(bytes(buf))
                        buf.clear()
                    self.msleep(5)
            except Exception as e:
                self.error.emit(str(e))
                break
        if buf:
            self.data_received.emit(bytes(buf))

    def stop(self):
        self._running = False
        self.wait(1000)


# ------------------------------------------------------------------ #
#  主窗口
# ------------------------------------------------------------------ #
class SerialTool(QMainWindow):
    COMMON_BAUDS = ["1200", "2400", "4800", "9600", "19200", "38400",
                    "57600", "115200", "230400", "460800", "921600"]
    DATA_BITS = ["8", "7", "6", "5"]
    PARITY_MAP = {
        "None (N)":  serial.PARITY_NONE,
        "Even (E)":  serial.PARITY_EVEN,
        "Odd  (O)":  serial.PARITY_ODD,
        "Mark (M)":  serial.PARITY_MARK,
        "Space (S)": serial.PARITY_SPACE,
    }
    STOP_MAP = {
        "1":   serial.STOPBITS_ONE,
        "1.5": serial.STOPBITS_ONE_POINT_FIVE,
        "2":   serial.STOPBITS_TWO,
    }
    MAX_HISTORY = 30

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Serial Debug Tool")
        self.resize(1200, 900)

        self.ser: serial.Serial | None = None
        self.reader: SerialReader | None = None
        self.log_file = None
        self.tx_bytes = 0
        self.rx_bytes = 0

        # 配置文件：优先程序同目录（便携），不可写时自动回退到用户目录
        self._config_path = config_path()
        self.settings = QSettings(self._config_path, QSettings.IniFormat)

        self._build_ui()
        self._apply_style()
        self._load_settings()

        # 启动时刷新一次，之后仅手动刷新
        self.refresh_ports()

        # 自动发送定时器
        self.auto_send_timer = QTimer(self)
        self.auto_send_timer.timeout.connect(self.on_send_clicked)

    # -------------------------------------------------------------- #
    #  UI
    # -------------------------------------------------------------- #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        # ============ 左侧：串口配置 ============
        cfg_box = QGroupBox("串口配置")
        g = QGridLayout(cfg_box)
        g.setVerticalSpacing(6)
        g.setHorizontalSpacing(6)

        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(150)
        self.btn_refresh = QToolButton()
        self.btn_refresh.setObjectName("refreshBtn")
        self.btn_refresh.setText("⟳")
        self.btn_refresh.setToolTip("刷新串口")
        self.btn_refresh.clicked.connect(self.refresh_ports)

        self.cmb_baud = QComboBox()
        self.cmb_baud.setEditable(True)  # 支持自定义
        self.cmb_baud.addItems(self.COMMON_BAUDS)
        self.cmb_baud.setValidator(QRegExpValidator(QRegExp(r"\d{1,7}")))

        self.cmb_data = QComboBox(); self.cmb_data.addItems(self.DATA_BITS)
        self.cmb_parity = QComboBox(); self.cmb_parity.addItems(list(self.PARITY_MAP.keys()))
        self.cmb_stop = QComboBox(); self.cmb_stop.addItems(list(self.STOP_MAP.keys()))

        self.btn_open = QPushButton("打开串口")
        self.btn_open.setCheckable(True)
        self.btn_open.setObjectName("openBtn")
        self.btn_open.clicked.connect(self.toggle_port)

        row = 0
        g.addWidget(QLabel("端口"), row, 0)
        g.addWidget(self.cmb_port, row, 1)
        g.addWidget(self.btn_refresh, row, 2); row += 1
        g.addWidget(QLabel("波特率"), row, 0); g.addWidget(self.cmb_baud, row, 1, 1, 2); row += 1
        g.addWidget(QLabel("数据位"), row, 0); g.addWidget(self.cmb_data, row, 1, 1, 2); row += 1
        g.addWidget(QLabel("校验位"), row, 0); g.addWidget(self.cmb_parity, row, 1, 1, 2); row += 1
        g.addWidget(QLabel("停止位"), row, 0); g.addWidget(self.cmb_stop, row, 1, 1, 2); row += 1
        g.addWidget(self.btn_open, row, 0, 1, 3); row += 1

        # ============ 显示选项 ============
        disp_box = QGroupBox("显示 / 日志")
        dl = QGridLayout(disp_box)
        self.chk_rx_hex = QCheckBox("接收 HEX 显示")
        self.chk_show_time = QCheckBox("显示时间戳 (ms)")
        self.chk_show_time.setChecked(True)
        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        self.chk_log_save = QCheckBox("保存日志到文件")
        self.btn_log_dir = QPushButton("日志目录…")
        self.btn_log_dir.clicked.connect(self.choose_log_dir)
        self.btn_clear = QPushButton("清空接收")
        self.btn_clear.clicked.connect(lambda: self.recv_edit.clear())

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(["浅色", "深色"])
        self.cmb_theme.currentTextChanged.connect(self._on_theme_changed)

        dl.addWidget(self.chk_rx_hex,     0, 0)
        dl.addWidget(self.chk_show_time,  0, 1)
        dl.addWidget(self.chk_autoscroll, 1, 0)
        dl.addWidget(self.chk_log_save,   1, 1)
        dl.addWidget(self.btn_log_dir,    2, 0)
        dl.addWidget(self.btn_clear,      2, 1)
        dl.addWidget(QLabel("皮肤"),      3, 0)
        dl.addWidget(self.cmb_theme,      3, 1)

        # ============ 发送区 ============
        send_box = QGroupBox("发送")
        sv = QVBoxLayout(send_box)

        # ---- 第 1 行：多行输入框（上移、加高） ----
        self.send_edit = QPlainTextEdit()
        self.send_edit.setPlaceholderText(
            "在此输入待发送内容（支持多行）…\nHEX 模式下请输入十六进制，如：AA 55 01 02")
        self.send_edit.setMinimumHeight(140)
        sv.addWidget(self.send_edit, 1)

        # ---- 第 2 行：历史 + 循环发送 + 发送按钮 ----
        hist_row = QHBoxLayout()
        self.cmb_history = QComboBox()
        self.cmb_history.setEditable(False)
        self.cmb_history.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.cmb_history.activated.connect(self.on_history_selected)

        self.chk_auto_send = QCheckBox("循环发送")
        self.spn_interval = QSpinBox()
        self.spn_interval.setRange(10, 600000)
        self.spn_interval.setValue(1000)
        self.spn_interval.setSuffix(" ms")
        self.spn_interval.setFixedWidth(130)
        self.chk_auto_send.toggled.connect(self.toggle_auto_send)

        self.btn_send = QPushButton("发  送")
        self.btn_send.setObjectName("sendBtn")
        self.btn_send.clicked.connect(self.on_send_clicked)

        hist_row.addWidget(QLabel("历史:"))
        hist_row.addWidget(self.cmb_history, 1)
        hist_row.addSpacing(8)
        hist_row.addWidget(self.chk_auto_send)
        hist_row.addWidget(self.spn_interval)
        hist_row.addSpacing(8)
        hist_row.addWidget(self.btn_send)
        sv.addLayout(hist_row)

        # ---- 第 3 行：发送选项 ----
        opt_row = QHBoxLayout()
        self.chk_tx_hex = QCheckBox("HEX 发送")
        self.chk_tx_newline = QCheckBox("附加 \\r\\n")
        opt_row.addWidget(self.chk_tx_hex)
        opt_row.addWidget(self.chk_tx_newline)
        opt_row.addStretch()
        sv.addLayout(opt_row)

        # ---- 第 4 行：校验设置 ----
        chk_row = QHBoxLayout()
        self.chk_checksum = QCheckBox("附加校验")
        self.cmb_checksum = QComboBox()
        self.cmb_checksum.addItems(CHECKSUM_TYPES)
        self.cmb_checksum.setCurrentText("SUM (1B)")
        self.spn_chk_start = QSpinBox()
        self.spn_chk_start.setRange(1, 9999)
        self.spn_chk_start.setValue(1)
        self.spn_chk_start.setPrefix("起:")
        self.spn_chk_end = QSpinBox()
        self.spn_chk_end.setRange(0, 9999)
        self.spn_chk_end.setValue(0)
        self.spn_chk_end.setPrefix("止:")
        self.spn_chk_end.setToolTip("0 表示到数据末尾")
        chk_row.addWidget(self.chk_checksum)
        chk_row.addWidget(self.cmb_checksum)
        chk_row.addWidget(self.spn_chk_start)
        chk_row.addWidget(self.spn_chk_end)
        chk_row.addWidget(QLabel("(字节, 1-based)"))
        chk_row.addStretch()
        sv.addLayout(chk_row)

        # ============ 自动回复 ============
        auto_box = QGroupBox("自动回复（匹配到接收内容后自动发送）")
        av = QVBoxLayout(auto_box)
        top_row = QHBoxLayout()
        self.chk_auto_reply = QCheckBox("启用自动回复")
        self.chk_reply_hex_match = QCheckBox("按 HEX 匹配")
        self.chk_reply_hex_send = QCheckBox("按 HEX 发送")
        top_row.addWidget(self.chk_auto_reply)
        top_row.addWidget(self.chk_reply_hex_match)
        top_row.addWidget(self.chk_reply_hex_send)
        top_row.addStretch()
        av.addLayout(top_row)

        self.reply_table = QTableWidget(0, 3)
        self.reply_table.setHorizontalHeaderLabels(["启用", "触发内容 (收到)", "回复内容 (发送)"])
        hh = self.reply_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.reply_table.verticalHeader().setDefaultSectionSize(26)
        self.reply_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        av.addWidget(self.reply_table)

        btn_row = QHBoxLayout()
        self.btn_add_rule = QPushButton("添加")
        self.btn_del_rule = QPushButton("删除所选")
        self.btn_add_rule.clicked.connect(lambda: self._add_reply_row("", "", True))
        self.btn_del_rule.clicked.connect(self._del_rule_rows)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_add_rule)
        btn_row.addWidget(self.btn_del_rule)
        av.addLayout(btn_row)

        # ============ 接收区 ============
        self.recv_edit = QTextEdit()
        self.recv_edit.setReadOnly(True)
        self.recv_edit.setFont(QFont("Consolas", 10))
        self.recv_edit.setLineWrapMode(QTextEdit.WidgetWidth)

        # ============ 总体布局 ============
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.addWidget(cfg_box)
        lv.addWidget(disp_box)
        lv.addStretch()

        right_top = QWidget()
        rtv = QVBoxLayout(right_top)
        rtv.setContentsMargins(0, 0, 0, 0)
        rtv.addWidget(QLabel("接收区："))
        rtv.addWidget(self.recv_edit)

        right_split = QSplitter(Qt.Vertical)
        right_split.addWidget(right_top)

        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        tab = QTabWidget()
        tab.addTab(send_box, "发送")
        tab.addTab(auto_box, "自动回复")
        tab.addTab(self._build_quick_tab(), "快捷按钮")
        bv.addWidget(tab)
        right_split.addWidget(bottom)
        right_split.setStretchFactor(0, 3)
        right_split.setStretchFactor(1, 2)

        main_split = QSplitter(Qt.Horizontal)
        main_split.addWidget(left)
        main_split.addWidget(right_split)
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        main_split.setSizes([270, 780])

        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(main_split)

        # ============ 状态栏 ============
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.lbl_state = QLabel("未连接")
        self.lbl_counter = QLabel("TX: 0  RX: 0")
        self.btn_reset_cnt = QPushButton("清零")
        self.btn_reset_cnt.setFlat(True)
        self.btn_reset_cnt.clicked.connect(self._reset_counter)
        self.lbl_version = QLabel(f"{__version__}  by {__author__}")
        self.lbl_version.setStyleSheet("color: #888;")
        self.status.addWidget(self.lbl_state, 1)
        self.status.addPermanentWidget(self.lbl_counter)
        self.status.addPermanentWidget(self.btn_reset_cnt)
        self.status.addPermanentWidget(self.lbl_version)

    # -------------------------------------------------------------- #
    #  样式 / 主题
    # -------------------------------------------------------------- #
    LIGHT_QSS = """
        QWidget { color: #202020; }
        QMainWindow, QDialog { background: #f5f6f8; }
        QGroupBox {
            border: 1px solid #c8c8c8; border-radius: 6px;
            margin-top: 10px; padding-top: 6px;
            font-weight: bold;
            background: #fafbfc;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 10px; padding: 0 4px;
            color: #2a6fb2;
        }
        QPushButton {
            padding: 5px 14px; border-radius: 4px;
            border: 1px solid #b5b5b5; background: #f7f7f7; color: #202020;
        }
        QPushButton:hover { background: #e8f1fb; border-color: #2a6fb2; }
        QPushButton:pressed { background: #d4e6f7; }
        QPushButton:disabled { color: #888; background: #eee; }
        QPushButton#openBtn:checked {
            background: #2a6fb2; color: white; border-color: #2a6fb2;
        }
        QPushButton#sendBtn {
            background: #2a6fb2; color: white; border-color: #2a6fb2;
            font-weight: bold; min-width: 80px;
        }
        QPushButton#sendBtn:hover { background: #3b83c9; }
        QToolButton {
            padding: 4px 8px; border-radius: 4px;
            border: 1px solid #b5b5b5; background: #f7f7f7; color: #202020;
            min-width: 24px;
        }
        QToolButton:hover { background: #e8f1fb; border-color: #2a6fb2; color: #2a6fb2; }
        QToolButton#refreshBtn { font-size: 16px; font-weight: bold; color: #2a6fb2; }
        QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {
            border: 1px solid #c8c8c8; border-radius: 3px;
            padding: 2px 4px; background: white; color: #202020;
            selection-background-color: #2a6fb2; selection-color: white;
        }
        QTextEdit { background: #fafafa; }
        /* ---- 下拉列表：不透明背景，避免覆盖文字 ---- */
        QComboBox QAbstractItemView {
            background: #ffffff;
            color: #202020;
            border: 1px solid #b5b5b5;
            selection-background-color: #2a6fb2;
            selection-color: white;
            outline: 0;
        }
        QTableWidget { gridline-color: #dcdcdc; background: white; color: #202020; }
        QHeaderView::section {
            background: #eef2f7; padding: 4px; color: #202020;
            border: none; border-right: 1px solid #dcdcdc;
        }
        QTabWidget::pane { border: 1px solid #c8c8c8; border-radius: 4px; top: -1px; }
        QTabBar::tab {
            padding: 6px 14px; background: #e9ecef; color: #202020;
            border: 1px solid #c8c8c8; border-bottom: none;
            border-top-left-radius: 4px; border-top-right-radius: 4px;
        }
        QTabBar::tab:selected { background: #fafbfc; color: #2a6fb2; }
        QStatusBar { background: #eef2f7; }
        QCheckBox { color: #202020; }
    """

    DARK_QSS = """
        QWidget { color: #e6e6e6; }
        QMainWindow, QDialog { background: #232629; }
        QGroupBox {
            border: 1px solid #3c4045; border-radius: 6px;
            margin-top: 10px; padding-top: 6px;
            font-weight: bold;
            background: #2b2f33;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 10px; padding: 0 4px;
            color: #5aa9e6;
        }
        QPushButton {
            padding: 5px 14px; border-radius: 4px;
            border: 1px solid #4a4f55; background: #343a40; color: #e6e6e6;
        }
        QPushButton:hover { background: #3f4850; border-color: #5aa9e6; }
        QPushButton:pressed { background: #2a3036; }
        QPushButton:disabled { color: #777; background: #2a2d30; }
        QPushButton#openBtn:checked {
            background: #1f6feb; color: white; border-color: #1f6feb;
        }
        QPushButton#sendBtn {
            background: #1f6feb; color: white; border-color: #1f6feb;
            font-weight: bold; min-width: 80px;
        }
        QPushButton#sendBtn:hover { background: #3b83d9; }
        QToolButton {
            padding: 4px 8px; border-radius: 4px;
            border: 1px solid #4a4f55; background: #343a40; color: #e6e6e6;
            min-width: 24px;
        }
        QToolButton:hover { background: #3f4850; border-color: #5aa9e6; color: #5aa9e6; }
        QToolButton#refreshBtn { font-size: 16px; font-weight: bold; color: #5aa9e6; }
        QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {
            border: 1px solid #4a4f55; border-radius: 3px;
            padding: 2px 4px; background: #1e2124; color: #e6e6e6;
            selection-background-color: #1f6feb; selection-color: white;
        }
        QTextEdit { background: #1a1c1f; }
        QComboBox QAbstractItemView {
            background: #2b2f33;
            color: #e6e6e6;
            border: 1px solid #4a4f55;
            selection-background-color: #1f6feb;
            selection-color: white;
            outline: 0;
        }
        QTableWidget { gridline-color: #3c4045; background: #1e2124; color: #e6e6e6; }
        QHeaderView::section {
            background: #2b2f33; padding: 4px; color: #e6e6e6;
            border: none; border-right: 1px solid #3c4045;
        }
        QTabWidget::pane { border: 1px solid #3c4045; border-radius: 4px; top: -1px; }
        QTabBar::tab {
            padding: 6px 14px; background: #2b2f33; color: #cfd2d5;
            border: 1px solid #3c4045; border-bottom: none;
            border-top-left-radius: 4px; border-top-right-radius: 4px;
        }
        QTabBar::tab:selected { background: #1e2124; color: #5aa9e6; }
        QStatusBar { background: #2b2f33; }
        QCheckBox { color: #e6e6e6; }
        QToolTip { color: #e6e6e6; background: #2b2f33; border: 1px solid #4a4f55; }
    """

    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        self._apply_theme(self.settings.value("theme", "浅色"))

    def _apply_theme(self, name: str):
        if name == "深色":
            self.setStyleSheet(self.DARK_QSS)
        else:
            self.setStyleSheet(self.LIGHT_QSS)

    def _on_theme_changed(self, name: str):
        self._apply_theme(name)
        self.settings.setValue("theme", name)

    # -------------------------------------------------------------- #
    #  快捷按钮标签页
    # -------------------------------------------------------------- #
    def _build_quick_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        self.quick_table = QTableWidget(0, 5)
        self.quick_table.setHorizontalHeaderLabels(
            ["名称", "内容", "HEX", "附加\\r\\n", "发送"])
        hh = self.quick_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.quick_table.verticalHeader().setDefaultSectionSize(28)
        self.quick_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        v.addWidget(self.quick_table)

        row = QHBoxLayout()
        btn_add = QPushButton("添加按钮")
        btn_del = QPushButton("删除所选")
        btn_add.clicked.connect(lambda: self._add_quick_row("新指令", "", False, False))
        btn_del.clicked.connect(self._del_quick_rows)
        row.addStretch()
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        v.addLayout(row)
        return w

    def _make_center_checkbox(self, checked: bool) -> QWidget:
        """返回一个居中显示的 QCheckBox（用于表格单元）。"""
        c = QWidget()
        cb = QCheckBox()
        cb.setChecked(checked)
        lay = QHBoxLayout(c)
        lay.addWidget(cb)
        lay.setAlignment(Qt.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)
        c.checkbox = cb  # type: ignore[attr-defined]
        return c

    def _cell_checkbox(self, widget: QWidget) -> QCheckBox | None:
        return getattr(widget, "checkbox", None) if widget else None

    def _add_quick_row(self, name: str, content: str, is_hex: bool, newline: bool):
        r = self.quick_table.rowCount()
        self.quick_table.insertRow(r)
        self.quick_table.setItem(r, 0, QTableWidgetItem(name))
        self.quick_table.setItem(r, 1, QTableWidgetItem(content))
        self.quick_table.setCellWidget(r, 2, self._make_center_checkbox(is_hex))
        self.quick_table.setCellWidget(r, 3, self._make_center_checkbox(newline))
        btn = QPushButton("发送")
        btn.clicked.connect(lambda _=False, b=btn: self._send_quick_row(b))
        self.quick_table.setCellWidget(r, 4, btn)

    def _send_quick_row(self, btn: QPushButton):
        # 通过按钮定位所在行
        for r in range(self.quick_table.rowCount()):
            if self.quick_table.cellWidget(r, 4) is btn:
                break
        else:
            return
        if not (self.ser and self.ser.is_open):
            QMessageBox.information(self, "提示", "请先打开串口。")
            return
        content_item = self.quick_table.item(r, 1)
        if not content_item:
            return
        text = content_item.text()
        if not text:
            return
        hex_cb = self._cell_checkbox(self.quick_table.cellWidget(r, 2))
        nl_cb = self._cell_checkbox(self.quick_table.cellWidget(r, 3))
        is_hex = bool(hex_cb and hex_cb.isChecked())
        add_nl = bool(nl_cb and nl_cb.isChecked())
        try:
            data = hex_str_to_bytes(text) if is_hex else text.encode("utf-8")
            if add_nl and not is_hex:
                data += b"\r\n"
            data = self._maybe_append_checksum(data)
            self.ser.write(data)
        except Exception as e:
            self.append_log(f"[快捷发送失败] {e}", color="#c0392b")
            return
        self.tx_bytes += len(data)
        self._update_counter()
        shown = bytes_to_hex_str(data) if is_hex else text
        ts = f"[{now_ms()}] " if self.chk_show_time.isChecked() else ""
        name = (self.quick_table.item(r, 0).text() if self.quick_table.item(r, 0) else "")
        self.append_log(f"{ts}>> [{name}] {shown}", color="#0d47a1")
        self._write_log_raw(
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} "
            f"TX[{name}] -> {shown}\n")

    def _del_quick_rows(self):
        rows = sorted({i.row() for i in self.quick_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.quick_table.removeRow(r)

    # -------------------------------------------------------------- #
    #  自动回复行辅助
    # -------------------------------------------------------------- #
    def _add_reply_row(self, trigger: str, reply: str, enabled: bool):
        r = self.reply_table.rowCount()
        self.reply_table.insertRow(r)
        self.reply_table.setCellWidget(r, 0, self._make_center_checkbox(enabled))
        self.reply_table.setItem(r, 1, QTableWidgetItem(trigger))
        self.reply_table.setItem(r, 2, QTableWidgetItem(reply))

    # -------------------------------------------------------------- #
    #  校验辅助
    # -------------------------------------------------------------- #
    def _maybe_append_checksum(self, data: bytes) -> bytes:
        if not self.chk_checksum.isChecked():
            return data
        return apply_checksum(
            data,
            self.cmb_checksum.currentText(),
            self.spn_chk_start.value(),
            self.spn_chk_end.value(),
        )

    # -------------------------------------------------------------- #
    #  端口
    # -------------------------------------------------------------- #
    def refresh_ports(self):
        current = self.cmb_port.currentText()
        ports = serial.tools.list_ports.comports()
        items = []
        for p in ports:
            desc = p.description if p.description and p.description != "n/a" else ""
            items.append(f"{p.device}" + (f"  ({desc})" if desc else ""))
        existing = [self.cmb_port.itemText(i) for i in range(self.cmb_port.count())]
        if items != existing:
            self.cmb_port.blockSignals(True)
            self.cmb_port.clear()
            self.cmb_port.addItems(items)
            # 恢复之前选择
            for i, it in enumerate(items):
                if it.split()[0] == current.split()[0] if current else False:
                    self.cmb_port.setCurrentIndex(i)
                    break
            self.cmb_port.blockSignals(False)

    def _current_port_device(self) -> str:
        txt = self.cmb_port.currentText().strip()
        return txt.split()[0] if txt else ""

    def toggle_port(self, checked):
        if checked:
            self.open_port()
        else:
            self.close_port()

    def open_port(self):
        dev = self._current_port_device()
        if not dev:
            QMessageBox.warning(self, "提示", "未选择串口。")
            self.btn_open.setChecked(False)
            return
        try:
            baud = int(self.cmb_baud.currentText())
        except ValueError:
            QMessageBox.warning(self, "提示", "波特率无效。")
            self.btn_open.setChecked(False)
            return
        try:
            self.ser = serial.Serial(
                port=dev,
                baudrate=baud,
                bytesize=int(self.cmb_data.currentText()),
                parity=self.PARITY_MAP[self.cmb_parity.currentText()],
                stopbits=self.STOP_MAP[self.cmb_stop.currentText()],
                timeout=0,
                write_timeout=1,
            )
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))
            self.btn_open.setChecked(False)
            return

        self.reader = SerialReader(self.ser)
        self.reader.data_received.connect(self.on_data_received)
        self.reader.error.connect(self.on_serial_error)
        self.reader.start()

        self.btn_open.setText("关闭串口")
        self.lbl_state.setText(
            f"已连接 {dev} @ {baud} {self.cmb_data.currentText()}"
            f"{self.cmb_parity.currentText()[0]}{self.cmb_stop.currentText()}"
        )
        self._set_config_enabled(False)

        if self.chk_log_save.isChecked():
            self._open_log_file()

    def close_port(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.btn_open.setText("打开串口")
        self.btn_open.setChecked(False)
        self.lbl_state.setText("未连接")
        self._set_config_enabled(True)
        self._close_log_file()

    def _set_config_enabled(self, enabled: bool):
        for w in (self.cmb_port, self.cmb_baud, self.cmb_data,
                  self.cmb_parity, self.cmb_stop, self.btn_refresh):
            w.setEnabled(enabled)

    def on_serial_error(self, msg):
        self.append_log(f"[错误] {msg}", color="#c0392b")
        self.close_port()

    # -------------------------------------------------------------- #
    #  日志
    # -------------------------------------------------------------- #
    def choose_log_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择日志目录",
            self.settings.value("log_dir", str(Path.home())))
        if d:
            self.settings.setValue("log_dir", d)
            self.status.showMessage(f"日志目录：{d}", 3000)

    def _log_dir(self) -> str:
        return self.settings.value("log_dir", os.path.join(app_dir(), "logs"))

    def _open_log_file(self):
        try:
            d = self._log_dir()
            os.makedirs(d, exist_ok=True)
            name = datetime.datetime.now().strftime("%Y-%m-%d") + ".log"
            self.log_file = open(os.path.join(d, name), "a", encoding="utf-8")
            self._write_log_raw(f"\n===== Session start {datetime.datetime.now()} =====\n")
        except Exception as e:
            self.log_file = None
            QMessageBox.warning(self, "日志", f"无法打开日志文件：{e}")

    def _close_log_file(self):
        if self.log_file:
            try:
                self._write_log_raw(f"===== Session end {datetime.datetime.now()} =====\n")
                self.log_file.close()
            except Exception:
                pass
            self.log_file = None

    def _write_log_raw(self, text: str):
        if self.log_file:
            try:
                self.log_file.write(text)
                self.log_file.flush()
            except Exception:
                pass

    # -------------------------------------------------------------- #
    #  接收
    # -------------------------------------------------------------- #
    def on_data_received(self, data: bytes):
        self.rx_bytes += len(data)
        self._update_counter()

        if self.chk_rx_hex.isChecked():
            shown = bytes_to_hex_str(data)
        else:
            try:
                shown = data.decode("utf-8")
            except UnicodeDecodeError:
                shown = data.decode("latin-1", errors="replace")

        ts = f"[{now_ms()}] " if self.chk_show_time.isChecked() else ""
        self.append_log(f"{ts}<< {shown}", color="#1b5e20")
        self._write_log_raw(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} RX <- {shown}\n")

        # 自动回复
        if self.chk_auto_reply.isChecked():
            self._check_auto_reply(data)

    def append_log(self, text: str, color: str = "#202020"):
        cursor = self.recv_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(text + "\n", fmt)
        if self.chk_autoscroll.isChecked():
            self.recv_edit.moveCursor(QTextCursor.End)

    # -------------------------------------------------------------- #
    #  发送
    # -------------------------------------------------------------- #
    def on_send_clicked(self):
        if not (self.ser and self.ser.is_open):
            if not self.chk_auto_send.isChecked():
                QMessageBox.information(self, "提示", "请先打开串口。")
            return
        text = self.send_edit.toPlainText()
        if not text:
            return
        try:
            if self.chk_tx_hex.isChecked():
                data = hex_str_to_bytes(text)
            else:
                data = text.encode("utf-8")
                if self.chk_tx_newline.isChecked():
                    data += b"\r\n"
            data = self._maybe_append_checksum(data)
            self.ser.write(data)
        except Exception as e:
            self.append_log(f"[发送失败] {e}", color="#c0392b")
            return

        self.tx_bytes += len(data)
        self._update_counter()
        shown = bytes_to_hex_str(data) if self.chk_tx_hex.isChecked() else text
        ts = f"[{now_ms()}] " if self.chk_show_time.isChecked() else ""
        self.append_log(f"{ts}>> {shown}", color="#0d47a1")
        self._write_log_raw(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} TX -> {shown}\n")

        self._push_history(text)

    def toggle_auto_send(self, on: bool):
        if on:
            self.auto_send_timer.start(self.spn_interval.value())
        else:
            self.auto_send_timer.stop()

    # -------------------------------------------------------------- #
    #  历史
    # -------------------------------------------------------------- #
    def _push_history(self, text: str):
        text = text.strip()
        if not text:
            return
        items = [self.cmb_history.itemText(i) for i in range(self.cmb_history.count())]
        if text in items:
            items.remove(text)
        items.insert(0, text)
        items = items[:self.MAX_HISTORY]
        self.cmb_history.blockSignals(True)
        self.cmb_history.clear()
        self.cmb_history.addItems(items)
        self.cmb_history.blockSignals(False)

    def on_history_selected(self, idx: int):
        if idx < 0:
            return
        self.send_edit.setPlainText(self.cmb_history.itemText(idx))

    # -------------------------------------------------------------- #
    #  自动回复
    # -------------------------------------------------------------- #
    def _del_rule_rows(self):
        rows = sorted({i.row() for i in self.reply_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.reply_table.removeRow(r)

    def _check_auto_reply(self, data: bytes):
        if not (self.ser and self.ser.is_open):
            return
        hex_match = self.chk_reply_hex_match.isChecked()
        hex_send = self.chk_reply_hex_send.isChecked()

        if hex_match:
            haystack = bytes_to_hex_str(data).replace(" ", "").upper()
        else:
            try:
                haystack = data.decode("utf-8", errors="replace")
            except Exception:
                haystack = ""

        for r in range(self.reply_table.rowCount()):
            en_cb = self._cell_checkbox(self.reply_table.cellWidget(r, 0))
            if not (en_cb and en_cb.isChecked()):
                continue
            trig_item = self.reply_table.item(r, 1)
            reply_item = self.reply_table.item(r, 2)
            if not trig_item or not reply_item:
                continue
            trig = trig_item.text()
            reply = reply_item.text()
            if not trig or not reply:
                continue

            if hex_match:
                needle = trig.replace(" ", "").upper()
                hit = needle and needle in haystack
            else:
                hit = trig in haystack

            if hit:
                try:
                    out = hex_str_to_bytes(reply) if hex_send else reply.encode("utf-8")
                    out = self._maybe_append_checksum(out)
                    self.ser.write(out)
                    self.tx_bytes += len(out)
                    self._update_counter()
                    shown = bytes_to_hex_str(out) if hex_send else reply
                    ts = f"[{now_ms()}] " if self.chk_show_time.isChecked() else ""
                    self.append_log(f"{ts}>> (auto) {shown}", color="#6a1b9a")
                    self._write_log_raw(
                        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} TX(auto) -> {shown}\n")
                except Exception as e:
                    self.append_log(f"[自动回复失败] {e}", color="#c0392b")

    # -------------------------------------------------------------- #
    #  计数器
    # -------------------------------------------------------------- #
    def _update_counter(self):
        self.lbl_counter.setText(f"TX: {self.tx_bytes}  RX: {self.rx_bytes}")

    def _reset_counter(self):
        self.tx_bytes = self.rx_bytes = 0
        self._update_counter()

    # -------------------------------------------------------------- #
    #  配置文件
    # -------------------------------------------------------------- #
    def _load_settings(self):
        s = self.settings
        baud = s.value("baud", "115200")
        idx = self.cmb_baud.findText(baud)
        if idx >= 0:
            self.cmb_baud.setCurrentIndex(idx)
        else:
            self.cmb_baud.setEditText(str(baud))
        self.cmb_data.setCurrentText(s.value("data", "8"))
        self.cmb_parity.setCurrentText(s.value("parity", "None (N)"))
        self.cmb_stop.setCurrentText(s.value("stop", "1"))

        self.chk_rx_hex.setChecked(s.value("rx_hex", False, type=bool))
        self.chk_tx_hex.setChecked(s.value("tx_hex", False, type=bool))
        self.chk_tx_newline.setChecked(s.value("tx_newline", False, type=bool))
        self.chk_show_time.setChecked(s.value("show_time", True, type=bool))
        self.chk_autoscroll.setChecked(s.value("autoscroll", True, type=bool))
        self.chk_log_save.setChecked(s.value("log_save", False, type=bool))

        theme = s.value("theme", "浅色")
        self.cmb_theme.blockSignals(True)
        self.cmb_theme.setCurrentText(theme)
        self.cmb_theme.blockSignals(False)

        self.spn_interval.setValue(int(s.value("auto_interval", 1000)))

        self.chk_auto_reply.setChecked(s.value("auto_reply", False, type=bool))
        self.chk_reply_hex_match.setChecked(s.value("reply_hex_match", False, type=bool))
        self.chk_reply_hex_send.setChecked(s.value("reply_hex_send", False, type=bool))

        # 校验
        self.chk_checksum.setChecked(s.value("chk_enable", False, type=bool))
        self.cmb_checksum.setCurrentText(s.value("chk_type", "SUM (1B)"))
        self.spn_chk_start.setValue(int(s.value("chk_start", 1)))
        self.spn_chk_end.setValue(int(s.value("chk_end", 0)))

        # 历史
        hist = s.value("history", [])
        if isinstance(hist, str):
            try:
                hist = json.loads(hist)
            except Exception:
                hist = [hist]
        if hist:
            self.cmb_history.addItems(list(hist))

        # 自动回复规则
        rules_raw = s.value("reply_rules", "[]")
        try:
            rules = json.loads(rules_raw) if isinstance(rules_raw, str) else rules_raw
        except Exception:
            rules = []
        for rule in rules or []:
            self._add_reply_row(
                rule.get("trigger", ""),
                rule.get("reply", ""),
                bool(rule.get("enabled", True)),
            )

        # 快捷按钮
        quicks_raw = s.value("quick_buttons", "[]")
        try:
            quicks = json.loads(quicks_raw) if isinstance(quicks_raw, str) else quicks_raw
        except Exception:
            quicks = []
        for q in quicks or []:
            self._add_quick_row(
                q.get("name", ""),
                q.get("content", ""),
                bool(q.get("hex", False)),
                bool(q.get("newline", False)),
            )

        last_send = s.value("last_send", "")
        if last_send:
            self.send_edit.setPlainText(last_send)

        geom = s.value("geometry")
        if geom:
            self.restoreGeometry(geom)

    def _save_settings(self):
        s = self.settings
        s.setValue("baud", self.cmb_baud.currentText())
        s.setValue("data", self.cmb_data.currentText())
        s.setValue("parity", self.cmb_parity.currentText())
        s.setValue("stop", self.cmb_stop.currentText())

        s.setValue("rx_hex", self.chk_rx_hex.isChecked())
        s.setValue("tx_hex", self.chk_tx_hex.isChecked())
        s.setValue("tx_newline", self.chk_tx_newline.isChecked())
        s.setValue("show_time", self.chk_show_time.isChecked())
        s.setValue("autoscroll", self.chk_autoscroll.isChecked())
        s.setValue("log_save", self.chk_log_save.isChecked())

        s.setValue("auto_interval", self.spn_interval.value())
        s.setValue("auto_reply", self.chk_auto_reply.isChecked())
        s.setValue("reply_hex_match", self.chk_reply_hex_match.isChecked())
        s.setValue("reply_hex_send", self.chk_reply_hex_send.isChecked())

        s.setValue("chk_enable", self.chk_checksum.isChecked())
        s.setValue("chk_type", self.cmb_checksum.currentText())
        s.setValue("chk_start", self.spn_chk_start.value())
        s.setValue("chk_end", self.spn_chk_end.value())

        hist = [self.cmb_history.itemText(i) for i in range(self.cmb_history.count())]
        s.setValue("history", json.dumps(hist, ensure_ascii=False))

        rules = []
        for r in range(self.reply_table.rowCount()):
            en_cb = self._cell_checkbox(self.reply_table.cellWidget(r, 0))
            t = self.reply_table.item(r, 1)
            p = self.reply_table.item(r, 2)
            rules.append({
                "enabled": bool(en_cb and en_cb.isChecked()),
                "trigger": t.text() if t else "",
                "reply": p.text() if p else "",
            })
        s.setValue("reply_rules", json.dumps(rules, ensure_ascii=False))

        quicks = []
        for r in range(self.quick_table.rowCount()):
            name_item = self.quick_table.item(r, 0)
            cont_item = self.quick_table.item(r, 1)
            hex_cb = self._cell_checkbox(self.quick_table.cellWidget(r, 2))
            nl_cb = self._cell_checkbox(self.quick_table.cellWidget(r, 3))
            quicks.append({
                "name": name_item.text() if name_item else "",
                "content": cont_item.text() if cont_item else "",
                "hex": bool(hex_cb and hex_cb.isChecked()),
                "newline": bool(nl_cb and nl_cb.isChecked()),
            })
        s.setValue("quick_buttons", json.dumps(quicks, ensure_ascii=False))

        s.setValue("last_send", self.send_edit.toPlainText())
        s.setValue("geometry", self.saveGeometry())

    # -------------------------------------------------------------- #
    def closeEvent(self, ev):
        try:
            self._save_settings()
        finally:
            self.close_port()
        super().closeEvent(ev)


# ------------------------------------------------------------------ #
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SerialDebugTool")
    w = SerialTool()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
