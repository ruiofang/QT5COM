import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import io
import pty
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import serial_tool as m


class SerialStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = m.QApplication.instance() or m.QApplication([])

    def test_continuous_input_delivered_before_stop_and_in_bounded_chunks(self):
        class BusySerial:
            in_waiting = 1000000
            reads = []
            def read(self, size):
                self.reads.append(size)
                if len(self.reads) == 30:
                    reader._running = False
                return b'x' * size
        ser = BusySerial()
        reader = m.SerialReader(ser)
        received = []
        reader.data_received.connect(lambda data: received.append((reader._running, data)))
        reader.run()
        self.assertTrue(received[0][0], 'continuous traffic must display before stop')
        self.assertEqual(b''.join(data for _, data in received), b'x' * sum(ser.reads))
        self.assertLessEqual(max(ser.reads), reader.MAX_CHUNK_BYTES)

    def test_deadline_flushes_even_when_continuously_busy_below_chunk_limit(self):
        class SmallSerial:
            in_waiting = 1
            reads = 0
            def read(self, size):
                self.reads += 1
                if self.reads == 12:
                    reader._running = False
                return b'a'
        ser = SmallSerial()
        reader = m.SerialReader(ser)
        received = []
        reader.data_received.connect(lambda data: received.append((ser.reads, data)))
        with patch.object(m.time, 'monotonic', side_effect=[i * .005 for i in range(13)]):
            reader.run()
        self.assertLessEqual(received[0][0], 5)
        self.assertEqual(b''.join(data for _, data in received), b'a' * 12)

    def make_window(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with patch.object(m, 'config_path', return_value=tmp.name + '/settings.ini'), \
             patch.object(m.serial.tools.list_ports, 'comports', return_value=[]):
            window = m.SerialTool()
        self.addCleanup(window.close)
        window.chk_rx_hex.setChecked(False)
        return window

    def test_history_bounded_for_long_lines_and_short_lines_log_complete(self):
        window = self.make_window()
        log = io.StringIO()
        window.log_file = log
        data = b'x' * 4096
        for _ in range(180):
            window.on_data_received(data)
        self.assertEqual(window.rx_bytes, 180 * len(data))
        self.assertLessEqual(len(window.recv_edit.toPlainText()), window.MAX_DISPLAY_CHARS)
        self.assertEqual(log.getvalue().count('x'), 180 * len(data))
        window.log_file = None
        for i in range(2200):
            window.append_log(f'line {i}')
        self.assertLessEqual(window.recv_edit.document().blockCount(), window.MAX_DISPLAY_BLOCKS)
        self.assertIn('line 2199', window.recv_edit.toPlainText())
        window.btn_clear.click()
        self.assertEqual(window.recv_edit.toPlainText(), '')

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX PTY')
    def test_live_pty_stream_updates_gui_without_idle_gap(self):
        window = self.make_window()
        window.show()
        master, slave = pty.openpty()
        ser = m.open_serial_connection(port=os.ttyname(slave), baudrate=921600, timeout=0)
        reader = m.SerialReader(ser)
        reader.data_received.connect(window.on_data_received)
        errors = []
        reader.error.connect(errors.append)
        sent = []
        def produce():
            # 1024 bytes every 5 ms: ~200 KB/s, above 921600-baud UART payload rate.
            for _ in range(400):
                packet = b'0123456789ABCDEF' * 64
                offset = 0
                while offset < len(packet):
                    offset += os.write(master, packet[offset:])
                sent.append(packet)
                time.sleep(.005)
        producer = threading.Thread(target=produce, daemon=True)
        beats = []
        timer = m.QTimer()
        timer.timeout.connect(lambda: beats.append(time.monotonic()))
        timer.start(10)
        reader.start()
        producer.start()
        saw_live = False
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                self.app.processEvents()
                if producer.is_alive() and window.rx_bytes:
                    saw_live = bool(window.recv_edit.toPlainText())
                if not producer.is_alive() and window.rx_bytes == sum(map(len, sent)):
                    break
                time.sleep(.001)
            self.assertFalse(producer.is_alive())
            self.assertTrue(saw_live)
            self.assertFalse(errors)
            self.assertEqual(window.rx_bytes, 400 * 1024)
            self.assertGreater(len(beats), 50)
            self.assertLess(max(b - a for a, b in zip(beats, beats[1:])), .5)
            print(f'PTY: {window.rx_bytes} bytes received; max GUI heartbeat gap '
                  f'{max(b - a for a, b in zip(beats, beats[1:])) * 1000:.1f} ms')
        finally:
            timer.stop()
            reader.stop()
            ser.close()
            os.close(master)
            os.close(slave)
            producer.join(timeout=1)
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
