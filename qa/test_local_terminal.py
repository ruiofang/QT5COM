import os
import tempfile
import time
import unittest
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from local_terminal import LocalTerminalPanel

APP = QApplication.instance() or QApplication([])

@unittest.skipUnless(os.name == 'posix', 'POSIX PTY required')
class LocalTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = LocalTerminalPanel()
        self.p.resize(900, 500); self.p.show()
        APP.processEvents()
        self.p.start('/bin/bash', self.temp.name)
        self.wait(lambda: self.p.output.toPlainText().strip())

    def wait(self, check, timeout=4):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            APP.processEvents(); QTest.qWait(10)
            if check():
                return
        self.fail('timeout: ' + self.p.output.toPlainText()[-500:])

    def command(self, text):
        QTest.keyClicks(self.p.output, text)
        QTest.keyClick(self.p.output, Qt.Key_Return)

    def tearDown(self):
        if self.p.process:
            self.p.stop(); self.wait(lambda: self.p.process is None)
        self.p.hide(); self.p.deleteLater(); APP.processEvents()
        self.temp.cleanup()

    def test_input_resize_interrupt_and_restart(self):
        self.p.resize_terminal(93, 27)
        path = Path(self.temp.name, 'size')
        self.command('stty size > size')
        self.wait(lambda: path.exists() and path.read_text().strip())
        self.assertEqual(path.read_text().strip(), '27 93')
        self.command('sleep 30')
        QTest.qWait(100)
        QTest.keyClick(self.p.output, Qt.Key_C, Qt.ControlModifier)
        self.command('printf done > done')
        self.wait(lambda: Path(self.temp.name, 'done').exists())
        self.command('exit')
        self.wait(lambda: self.p.process is None)
        self.p.start('/bin/bash', self.temp.name)
        self.command('printf restarted > again')
        self.wait(lambda: Path(self.temp.name, 'again').exists())

    def test_vi_keyboard_and_large_final_output(self):
        if not Path('/usr/bin/vim.tiny').exists():
            self.skipTest('vim.tiny unavailable')
        self.command('vim.tiny -u NONE -i NONE -n result')
        QTest.qWait(200)
        QTest.keyClicks(self.p.output, 'iabcX')
        QTest.keyClick(self.p.output, Qt.Key_Backspace)
        QTest.keyClick(self.p.output, Qt.Key_Escape)
        QTest.qWait(100)
        self.command(':wq')
        path = Path(self.temp.name, 'result')
        self.wait(lambda: path.exists())
        self.assertEqual(path.read_text(), 'abc\n')
        self.command("printf '%100000s' x; printf 'END_MARKER'; exit")
        self.wait(lambda: self.p.process is None, 8)
        self.assertIn('END_MARKER', self.p.output.toPlainText())

    def test_close_stops_foreground_job(self):
        path = Path(self.temp.name, 'pid')
        self.command("sh -c 'echo $$ > pid; exec sleep 30'")
        self.wait(lambda: path.exists() and path.read_text().strip())
        pid = int(path.read_text())
        self.p.stop(); self.wait(lambda: self.p.process is None)
        # A killed child may briefly be a zombie until its new parent reaps it.
        stat = Path('/proc') / str(pid) / 'stat'
        self.assertTrue(not stat.exists() or stat.read_text().split()[2] == 'Z')

if __name__ == '__main__':
    unittest.main()
