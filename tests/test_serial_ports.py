import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import serial_tool as m


def port(device, description="USB Serial"):
    return SimpleNamespace(device=device, description=description)


class SerialPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = m.QApplication.instance() or m.QApplication([])

    def make_window(self, ports):
        tmp = tempfile.TemporaryDirectory()
        settings = str(Path(tmp.name) / "settings.ini")
        with patch.object(m, "config_path", return_value=settings), \
             patch.object(m.serial.tools.list_ports, "comports", return_value=ports), \
             patch.object(m, "serial_port_usability",
                          side_effect=lambda p: ("good" in p.device,
                                                 "可用" if "good" in p.device else "无权限")):
            window = m.SerialTool()
        return tmp, window

    def test_default_list_only_contains_usable_ports(self):
        tmp, window = self.make_window([
            port("/dev/bad0", "Phantom"), port("/dev/good0", "USB Adapter")])
        try:
            self.assertEqual(window.cmb_port.count(), 1)
            self.assertEqual(window._current_port_device(), "/dev/good0")
            self.assertIn("USB Adapter", window.cmb_port.currentText())
            self.assertIn("已隐藏 1", window.status.currentMessage())
        finally:
            window.close()
            tmp.cleanup()

    def test_show_all_marks_unusable_and_prevents_open(self):
        tmp, window = self.make_window([
            port("/dev/bad0", "Phantom"), port("/dev/good0")])
        try:
            with patch.object(m.serial.tools.list_ports, "comports",
                              return_value=[port("/dev/bad0", "Phantom"), port("/dev/good0")]), \
                 patch.object(m, "serial_port_usability",
                              side_effect=lambda p: ("good" in p.device,
                                                     "可用" if "good" in p.device else "无权限")):
                window.chk_show_all_ports.setChecked(True)
            self.assertEqual(window.cmb_port.count(), 2)
            self.assertIn("不可用：无权限", window.cmb_port.itemText(0))
            window.cmb_port.setCurrentIndex(0)
            with patch.object(m.QMessageBox, "warning") as warning, \
                 patch.object(m.serial, "Serial") as serial_open:
                window.open_port()
            warning.assert_called_once()
            serial_open.assert_not_called()
        finally:
            window.close()
            tmp.cleanup()

    def test_linux_filter_checks_node_permission_and_uart(self):
        candidate = port("/dev/ttyS9")
        with patch.object(m.sys, "platform", "linux"), \
             patch.object(m.os.path, "exists", return_value=False):
            self.assertEqual(m.serial_port_usability(candidate),
                             (False, "设备节点不存在"))
        with patch.object(m.sys, "platform", "linux"), \
             patch.object(m.os.path, "exists", return_value=True), \
             patch.object(m.os, "access", return_value=False):
            self.assertEqual(m.serial_port_usability(candidate),
                             (False, "当前用户无读写权限"))
        with patch.object(m.sys, "platform", "linux"), \
             patch.object(m.os.path, "exists", return_value=True), \
             patch.object(m.os, "access", return_value=True), \
             patch.object(m, "_linux_uart_is_real", return_value=False):
            self.assertEqual(m.serial_port_usability(candidate),
                             (False, "内核未检测到 UART 硬件"))

    def test_all_traditional_ttys_are_ambiguous(self):
        for index in (0, 1, 31, 99):
            self.assertFalse(m._linux_uart_is_real(f"/dev/ttyS{index}"))
        self.assertTrue(m._linux_uart_is_real("/dev/ttyUSB0"))
        self.assertTrue(m._linux_uart_is_real("/dev/ttyACM0"))

    def test_open_failure_removes_port_for_current_run(self):
        ports = [port("/dev/good0")]
        tmp, window = self.make_window(ports)
        try:
            with patch.object(m.serial, "Serial", side_effect=OSError(5, "I/O error")), \
                 patch.object(m.QMessageBox, "critical"), \
                 patch.object(m.serial.tools.list_ports, "comports", return_value=ports), \
                 patch.object(m, "serial_port_usability", return_value=(True, "可用")):
                window.open_port()
            self.assertIn("/dev/good0", window.failed_ports)
            self.assertEqual(window.cmb_port.count(), 0)
            self.assertIn("未检测到可用串口", window.status.currentMessage())
        finally:
            window.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
