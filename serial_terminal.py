"""Interactive VT console over the application's existing serial port."""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                            QComboBox, QApplication)
from ssh_terminal import SSHTerminal


class SerialTerminalPanel(QWidget):
    def __init__(self, send, toggle_port, parent=None):
        super().__init__(parent)
        self.send = send
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.status = QLabel()
        self.open_button = QPushButton('打开串口')
        self.open_button.clicked.connect(toggle_port)
        clear = QPushButton('清空终端')
        self.output = SSHTerminal()
        self.output.responses_enabled = False
        self.output.data_ready.connect(self.send_input)
        clear.clicked.connect(self.output.clear)
        row.addWidget(self.status, 1)
        row.addWidget(self.open_button)
        row.addWidget(clear)
        layout.addLayout(row)
        layout.addWidget(self.output, 1)
        row = QHBoxLayout()
        self.newline = QComboBox()
        for label, data in [('CR', b'\r'), ('LF', b'\n'), ('CRLF', b'\r\n')]:
            self.newline.addItem(label, data)
        self.newline.currentIndexChanged.connect(self.update_keys)
        self.backspace = QComboBox()
        self.backspace.addItem('DEL (0x7F)', b'\x7f')
        self.backspace.addItem('BS (0x08)', b'\x08')
        self.backspace.currentIndexChanged.connect(self.update_keys)
        self.dimensions = QLabel()
        self.output.size_changed.connect(self.update_dimensions)
        copy_size = QPushButton('复制尺寸命令')
        copy_size.setToolTip('复制 TERM 和 stty 设置命令；登录 Linux 后按需粘贴执行，不会自动发送。')
        copy_size.clicked.connect(self.copy_size_command)
        self.interrupt_button = QPushButton('Ctrl+C')
        self.interrupt_button.clicked.connect(lambda: self.send_input(b'\x03'))
        row.addWidget(QLabel('Enter'))
        row.addWidget(self.newline)
        row.addWidget(QLabel('退格'))
        row.addWidget(self.backspace)
        row.addStretch()
        row.addWidget(self.dimensions)
        row.addWidget(copy_size)
        row.addWidget(self.interrupt_button)
        layout.addLayout(row)
        hint = QLabel('点击终端直接输入；Enter 登录/执行 · Tab 补全 · ↑↓ 历史 · Ctrl+C 中断 · Ctrl+Shift+C/V 复制/粘贴。\n'
                      '不需要 IP。输入由设备回显，本地不记录发送内容；串口窗口尺寸需在设备端按需设置。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.update_dimensions(self.output.screen.columns, self.output.screen.lines)
        self.set_connected(False)

    def update_keys(self):
        self.output.return_bytes = self.newline.currentData()
        self.output.backspace_bytes = self.backspace.currentData()

    def update_dimensions(self, columns, lines):
        self.dimensions.setText(f'{columns} 列 × {lines} 行')

    def copy_size_command(self):
        screen = self.output.screen
        QApplication.clipboard().setText(f'export TERM=xterm-256color; stty cols {screen.columns} rows {screen.lines}')
        self.output.setFocus()

    def set_connected(self, connected, description=''):
        self.status.setText(('已连接 ' + description) if connected else '未连接：请在左侧设置串口并打开。无需 IP。')
        self.open_button.setText('关闭串口' if connected else '打开串口')
        self.output.set_connected(connected)
        self.interrupt_button.setEnabled(connected)
        if connected:
            self.output.reset_stream()
            self.output.setFocus()
        else:
            # Keep the final screen available for diagnosis after disconnect.
            self.output.decoder.reset()

    def send_input(self, data):
        if not self.output.connected:
            return False
        if len(data) > 4096:
            self.output.append_notice('[本次输入超过 4096 字节，请分段粘贴]')
            return False
        # Direct input includes passwords, so never persist its contents locally.
        return self.send(data, True)
