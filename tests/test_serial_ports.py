import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import pty
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

    def test_kernel_uart_detection_keeps_real_ttys(self):
        table = "0: uart:16550A port:000003F8 irq:4\n1: uart:unknown port:00000000 irq:0\n"
        with patch.object(m.Path, "read_text", return_value=table):
            self.assertTrue(m._linux_uart_is_real("/dev/ttyS0"))
            self.assertFalse(m._linux_uart_is_real("/dev/ttyS1"))
            self.assertFalse(m._linux_uart_is_real("/dev/ttyS31"))
        self.assertTrue(m._linux_uart_is_real("/dev/ttyUSB0"))
        self.assertTrue(m._linux_uart_is_real("/dev/ttyACM0"))

    def test_termios_probe_accepts_a_configurable_terminal(self):
        master, slave = pty.openpty()
        try:
            self.assertEqual(m._probe_linux_tty(os.ttyname(slave)), (True, "可用"))
        finally:
            os.close(master)
            os.close(slave)
        usable, reason = m._probe_linux_tty("/definitely/not/a/tty")
        self.assertFalse(usable)
        self.assertIn("探测失败", reason)

    def test_real_ttys_must_also_pass_configuration_probe(self):
        candidate = port("/dev/ttyS0")
        common = [patch.object(m.sys, "platform", "linux"),
                  patch.object(m.os.path, "exists", return_value=True),
                  patch.object(m.os, "access", return_value=True),
                  patch.object(m, "_linux_uart_is_real", return_value=True)]
        with common[0], common[1], common[2], common[3], \
             patch.object(m, "_probe_linux_tty", return_value=(True, "可用")):
            self.assertEqual(m.serial_port_usability(candidate), (True, "可用"))
        with patch.object(m.sys, "platform", "linux"), \
             patch.object(m.os.path, "exists", return_value=True), \
             patch.object(m.os, "access", return_value=True), \
             patch.object(m, "_linux_uart_is_real", return_value=True), \
             patch.object(m, "_probe_linux_tty", return_value=(False, "端口配置探测失败：I/O error")):
            self.assertEqual(m.serial_port_usability(candidate),
                             (False, "端口配置探测失败：I/O error"))

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

    @unittest.skipUnless(os.name == "posix", "POSIX exclusive serial test")
    def test_same_port_cannot_be_opened_twice(self):
        master, slave = pty.openpty()
        device = os.ttyname(slave)
        first = None
        try:
            first = m.open_serial_connection(port=device, timeout=0)
            with self.assertRaises(m.serial.SerialException):
                m.open_serial_connection(port=device, timeout=0)
        finally:
            if first is not None:
                first.close()
            os.close(master)
            os.close(slave)

    def test_exclusive_flag_is_used_only_on_posix(self):
        with patch.object(m.os, "name", "posix"), \
             patch.object(m.serial, "Serial", return_value="opened") as serial_open:
            self.assertEqual(m.open_serial_connection(port="test"), "opened")
            self.assertTrue(serial_open.call_args.kwargs["exclusive"])
        with patch.object(m.os, "name", "nt"), \
             patch.object(m.serial, "Serial", return_value="opened") as serial_open:
            m.open_serial_connection(port="COM1")
            self.assertNotIn("exclusive", serial_open.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
