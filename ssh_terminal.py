"""Qt VT terminal: pyte screen model, bounded history and direct keyboard input."""
import copy
import codecs
import math
import re

import pyte
from wcwidth import wcswidth
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QAbstractScrollArea, QApplication, QMenu


class TerminalScreen(pyte.HistoryScreen):
    """Add xterm's alternate screen and terminal response callback to pyte."""
    STATE = ('savepoints', 'columns', 'lines', 'buffer', 'dirty', 'margins',
             'mode', 'title', 'icon_name', 'charset', 'g0_charset', 'g1_charset',
             'tabstops', 'cursor', 'saved_columns', 'history')

    def __init__(self, columns, lines, reply):
        self.primary = None
        self.reply = reply
        super().__init__(columns, lines, history=2000)

    def write_process_input(self, data):
        self.reply(data.encode('utf-8'))

    def resize(self, lines=None, columns=None):
        lines, columns = lines or self.lines, columns or self.columns
        if (lines, columns) == (self.lines, self.columns):
            return
        # Remove unused bottom rows before scrolling away text above the cursor.
        # This also preserves the primary prompt when leaving a resized alt screen.
        if lines < self.lines:
            drop = max(0, self.cursor.y - lines + 1)
            old = dict(self.buffer)
            if self.primary is None:
                for y in range(drop):
                    self.history.top.append(self.buffer[y])
            self.buffer.clear()
            for y in range(lines):
                if y + drop in old:
                    self.buffer[y] = old[y + drop]
            self.cursor.y -= drop
        if columns < self.columns:
            for row in self.buffer.values():
                for x in list(row):
                    if x >= columns:
                        del row[x]
        self.lines, self.columns = lines, columns
        self.cursor.x = min(self.cursor.x, columns - 1)
        self.cursor.y = min(self.cursor.y, lines - 1)
        self.set_margins()
        self.dirty.update(range(lines))

    def set_mode(self, *modes, **kwargs):
        if kwargs.get('private') and any(m in (47, 1047, 1049) for m in modes):
            if self.primary is None:
                self.primary = {name: copy.deepcopy(getattr(self, name)) for name in self.STATE}
                # Reset the alternate screen without mutating the saved primary.
                super().reset()
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        if kwargs.get('private') and any(m in (47, 1047, 1049) for m in modes):
            if self.primary is not None:
                columns, lines = self.columns, self.lines
                for name, value in self.primary.items():
                    setattr(self, name, value)
                self.primary = None
                self.resize(lines=lines, columns=columns)
                self.dirty.update(range(self.lines))
        super().reset_mode(*modes, **kwargs)


class SSHTerminal(QAbstractScrollArea):
    data_ready = pyqtSignal(bytes)
    size_changed = pyqtSignal(int, int)
    COLORS = {
        'black': '#1b1d23', 'red': '#e06c75', 'green': '#98c379',
        'brown': '#e5c07b', 'blue': '#61afef', 'magenta': '#c678dd',
        'cyan': '#56b6c2', 'white': '#abb2bf', 'brightblack': '#5c6370',
        'brightred': '#ff7a85', 'brightgreen': '#b5e890', 'brightbrown': '#ffe19a',
        'brightblue': '#8bcaff', 'brightmagenta': '#dfa3ff',
        'brightcyan': '#83e4ee', 'brightwhite': '#ffffff',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont('monospace', 11)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        metrics = QFontMetrics(font)
        self.cell_width = max(1, metrics.horizontalAdvance('M'))
        self.cell_height = max(1, math.ceil(metrics.height() * 1.12))
        self.ascent = metrics.ascent()
        self.connected = False
        self.responses_enabled = True
        self.return_bytes = b'\r'
        self.backspace_bytes = b'\x7f'
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.selection = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumSize(300, 160)
        self.screen = TerminalScreen(80, 24, self._reply)
        self.stream = pyte.Stream(self.screen)
        self.verticalScrollBar().valueChanged.connect(lambda _: self.viewport().update())
        self.setToolTip('直接输入；Ctrl+C 中断；Ctrl+Shift+C 复制；Ctrl+Shift+V 粘贴')

    def set_connected(self, connected):
        self.connected = connected
        self.viewport().update()

    def reset_stream(self):
        self.decoder.reset()
        self.screen = TerminalScreen(self.screen.columns, self.screen.lines, self._reply)
        self.stream = pyte.Stream(self.screen)
        self.selection = None
        self._refresh()

    def clear(self):
        # Local clear must preserve remote terminal modes (e.g. application keys).
        self.screen.erase_in_display(2)
        self.screen.cursor_position()
        self.screen.history.top.clear()
        self.screen.history.bottom.clear()
        self.selection = None
        self._refresh()

    def append_output(self, text):
        self.stream.feed(text)
        self._refresh()

    def feed(self, data):
        self.append_output(self.decoder.decode(data))

    def _reply(self, data):
        if self.responses_enabled:
            self._send(data)

    def append_notice(self, text):
        # Application diagnostics are text, never terminal control sequences.
        self.append_output('\r\n' + ''.join(c for c in text if c >= ' ') + '\r\n')

    def _refresh(self):
        scroll = self.verticalScrollBar()
        bottom = scroll.value() == scroll.maximum()
        scroll.setRange(0, 0 if self.screen.primary is not None else len(self.screen.history.top))
        scroll.setPageStep(self.screen.lines)
        if bottom:
            scroll.setValue(scroll.maximum())
        self.screen.dirty.clear()
        self.viewport().update()

    def _lines(self):
        history = [] if self.screen.primary is not None else list(self.screen.history.top)
        return history + [self.screen.buffer[y] for y in range(self.screen.lines)]

    def toPlainText(self):
        return '\n'.join(''.join(line[x].data for x in range(self.screen.columns)).rstrip()
                         for line in self._lines()).rstrip()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'screen'):
            return
        columns = max(20, min(240, (self.viewport().width() - 8) // self.cell_width))
        lines = max(4, min(120, (self.viewport().height() - 8) // self.cell_height))
        if (columns, lines) != (self.screen.columns, self.screen.lines):
            self.screen.resize(lines=lines, columns=columns)
            self.screen.cursor.x = min(self.screen.cursor.x, columns - 1)
            self.screen.cursor.y = min(self.screen.cursor.y, lines - 1)
            self.selection = None
            self._refresh()
            self.size_changed.emit(columns, lines)

    def _color(self, name, background=False, bold=False):
        if name == 'default':
            return QColor('#171a21' if background else '#d8dee9')
        if bold and not background and 'bright' + name in self.COLORS:
            name = 'bright' + name
        if name in self.COLORS:
            return QColor(self.COLORS[name])
        return QColor('#' + name) if re.fullmatch('[0-9a-fA-F]{6}', name) else QColor('#d8dee9')

    def _selected(self, row, column):
        if not self.selection:
            return False
        start, end = sorted(self.selection)
        return start <= (row, column) < end

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QColor('#171a21'))
        rows = self._lines()
        offset = self.verticalScrollBar().value()
        for y in range(self.screen.lines):
            row = rows[offset + y] if offset + y < len(rows) else {}
            x = 0
            while x < self.screen.columns:
                char = row.get(x, self.screen.default_char)
                if char.data == '':
                    x += 1
                    continue
                width = max(1, wcswidth(char.data))
                fg, bg = self._color(char.fg, bold=char.bold), self._color(char.bg, True)
                if char.reverse:
                    fg, bg = bg, fg
                if self._selected(offset + y, x):
                    bg = QColor('#375a7f')
                rect = QRect(4 + x * self.cell_width, 4 + y * self.cell_height,
                             self.cell_width * width, self.cell_height)
                painter.fillRect(rect, bg)
                if char.data != ' ':
                    font = self.font()
                    font.setBold(char.bold)
                    font.setItalic(char.italics)
                    font.setUnderline(char.underscore)
                    font.setStrikeOut(char.strikethrough)
                    painter.setFont(font)
                    painter.setPen(fg)
                    painter.drawText(rect.x(), rect.y() + self.ascent, char.data)
                x += width
        if offset == self.verticalScrollBar().maximum() and not self.screen.cursor.hidden:
            cursor = self.screen.cursor
            rect = QRect(4 + min(cursor.x, self.screen.columns - 1) * self.cell_width,
                         4 + cursor.y * self.cell_height, self.cell_width, self.cell_height)
            painter.setPen(QPen(QColor('#88c0d0' if self.connected else '#5c6370')))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _send(self, data):
        if self.connected:
            self.selection = None
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
            self.data_ready.emit(data)

    def event(self, event):
        # QWidget otherwise consumes Tab for focus navigation.
        if event.type() == event.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        if mods & Qt.ControlModifier and mods & Qt.ShiftModifier:
            if key == Qt.Key_C:
                self.copy_selection()
                return
            if key == Qt.Key_V:
                self.paste()
                return
        if mods & Qt.ShiftModifier and key in (Qt.Key_PageUp, Qt.Key_PageDown):
            delta = self.screen.lines * (-1 if key == Qt.Key_PageUp else 1)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta)
            return
        app_cursor = (1 << 5) in self.screen.mode
        prefix = b'\x1bO' if app_cursor else b'\x1b['
        keys = {Qt.Key_Return: self.return_bytes, Qt.Key_Enter: self.return_bytes, Qt.Key_Backspace: self.backspace_bytes,
                Qt.Key_Tab: b'\t', Qt.Key_Backtab: b'\x1b[Z', Qt.Key_Escape: b'\x1b',
                Qt.Key_Up: prefix + b'A', Qt.Key_Down: prefix + b'B',
                Qt.Key_Right: prefix + b'C', Qt.Key_Left: prefix + b'D',
                Qt.Key_Home: prefix + b'H', Qt.Key_End: prefix + b'F',
                Qt.Key_Insert: b'\x1b[2~', Qt.Key_Delete: b'\x1b[3~',
                Qt.Key_PageUp: b'\x1b[5~', Qt.Key_PageDown: b'\x1b[6~'}
        for i, suffix in enumerate((b'OP', b'OQ', b'OR', b'OS', b'[15~', b'[17~',
                                    b'[18~', b'[19~', b'[20~', b'[21~', b'[23~', b'[24~')):
            keys[Qt.Key_F1 + i] = b'\x1b' + suffix
        if mods & Qt.ControlModifier and Qt.Key_A <= key <= Qt.Key_Z:
            data = bytes([key - Qt.Key_A + 1])
        elif mods & Qt.ControlModifier and key in (Qt.Key_Space, Qt.Key_At):
            data = b'\x00'
        elif mods & Qt.ControlModifier and Qt.Key_BracketLeft <= key <= Qt.Key_Underscore:
            data = bytes([key - 64])
        else:
            data = keys.get(key, event.text().encode('utf-8'))
            if mods & Qt.AltModifier:
                data = b'\x1b' + data
        if data:
            self._send(data)
        event.accept()

    def inputMethodEvent(self, event):
        if event.commitString():
            self._send(event.commitString().encode('utf-8'))
        event.accept()

    def inputMethodQuery(self, query):
        if query == Qt.ImCursorRectangle:
            return QRect(4 + self.screen.cursor.x * self.cell_width,
                         4 + self.screen.cursor.y * self.cell_height,
                         self.cell_width, self.cell_height)
        return super().inputMethodQuery(query)

    def paste(self):
        text = QApplication.clipboard().text().replace('\r\n', '\n').replace('\r', '\n')
        if not text:
            return
        # Do not turn clipboard control bytes into injected terminal key sequences.
        text = ''.join(c for c in text if c in '\n\t' or c >= ' ')
        data = text.encode('utf-8').replace(b'\n', self.return_bytes)
        if (2004 << 5) in self.screen.mode:
            data = b'\x1b[200~' + data + b'\x1b[201~'
        self._send(data)

    def _position(self, point):
        return (max(0, min(self.screen.lines - 1, (point.y() - 4) // self.cell_height))
                + self.verticalScrollBar().value(),
                max(0, min(self.screen.columns, (point.x() - 4) // self.cell_width)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus()
            pos = self._position(event.pos())
            self.selection = (pos, pos)
            self.viewport().update()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.selection:
            self.selection = (self.selection[0], self._position(event.pos()))
            self.viewport().update()

    def copy_selection(self):
        if not self.selection:
            return
        start, end = sorted(self.selection)
        rows, text = self._lines(), []
        for y in range(start[0], min(end[0] + 1, len(rows))):
            first = start[1] if y == start[0] else 0
            last = end[1] if y == end[0] else self.screen.columns
            text.append(''.join(rows[y][x].data for x in range(first, last)).rstrip())
        QApplication.clipboard().setText('\n'.join(text))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy_action = menu.addAction('复制（Ctrl+Shift+C）', self.copy_selection)
        copy_action.setEnabled(bool(self.selection))
        paste_action = menu.addAction('粘贴（Ctrl+Shift+V）', self.paste)
        paste_action.setEnabled(self.connected)
        menu.exec_(event.globalPos())
