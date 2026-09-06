import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import serial_tool as m

SAMPLE = Path(__file__).resolve().parents[1] / 'mbp' / '夹爪.mbp'


def response(body):
    return body + m.calc_crc16_modbus(body)


class ModbusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = m.QApplication.instance() or m.QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with patch.object(m, 'config_path', return_value=self.tmp.name + '/settings.ini'):
            self.w = m.SerialTool()
        with patch.object(m.QFileDialog, 'getOpenFileName', return_value=(str(SAMPLE), '')):
            self.w.on_modbus_open_profile()

    def tearDown(self):
        self.w.close()
        self.tmp.cleanup()

    def connect_fake(self):
        class Serial:
            is_open = True
            frames = None
            def __init__(self):
                self.frames = []
            def write(self, data):
                self.frames.append(data)
                return len(data)
            def close(self):
                self.is_open = False
        self.w.ser = Serial()
        return self.w.ser

    def test_sample_matches_screenshot(self):
        p = m.parse_binary_mbp_profile(SAMPLE.read_bytes())
        self.assertEqual((p['slave_id'], p['function_code'], p['start_address'], p['quantity'], p['scan_rate']),
                         (1, 3, 4000, 32, 1000))
        self.assertEqual([e['value'] for e in p['entries']], [3, 0, 0, 247, 255, 0] + [65535] * 24 + [0, 0])
        self.assertEqual(self.w.modbus_table.horizontalHeaderItem(1).text(), '0FA0')
        self.assertEqual(self.w.modbus_table.horizontalHeaderItem(3).text(), '0FB0')
        self.assertEqual(self.w.modbus_table.item(1, 2).text(), '预设力矩寄存器4')
        self.assertEqual(self.w.modbus_table.item(1, 3).text(), '-1')
        self.assertEqual(self.w.modbus_table.item(15, 2).text(), '停止控制寄存器')
        frame = m.build_modbus_rtu_request(1, 3, 4000, 32)
        self.assertEqual(frame[:6], bytes.fromhex('01 03 0F A0 00 20'))

    def test_reject_damaged_or_unknown_profiles(self):
        data = SAMPLE.read_bytes()
        for bad in (data[:20], data[:-1], b'xxxx' + data[4:], data[:572] + b'xxxx' + data[576:]):
            self.assertIsNone(m.parse_binary_mbp_profile(bad))

    def test_empty_and_duplicate_names_keep_positions(self):
        data = SAMPLE.read_bytes()
        # Replace the first CString with empty; subsequent structures move with it.
        empty = data[:575] + b'\x00' + data[588:]
        profile = m.parse_binary_mbp_profile(empty)
        self.assertEqual(profile['entries'][0]['comment'], '')
        self.assertEqual(profile['entries'][1]['address'], 4001)
        self.assertEqual(profile['entries'][3]['value'], 247)
        duplicate = data[:782] + data[716:726] + data[792:]
        profile = m.parse_binary_mbp_profile(duplicate)
        self.assertEqual(len(profile['entries']), 32)
        self.assertEqual(profile['entries'][2]['comment'], profile['entries'][3]['comment'])

    def test_fill_does_not_send_and_fragmented_response(self):
        ser = self.connect_fake()
        self.w.on_modbus_fill_send_clicked()
        self.assertEqual(ser.frames, [])
        self.assertIsNone(self.w.pending_modbus_request)
        self.w.on_modbus_read_clicked()
        self.assertEqual(len(ser.frames), 1)
        frame = response(bytes([1, 3, 64]) + struct.pack('>32H', *range(32)))
        for byte in frame[:-1]:
            self.w.on_data_received(bytes([byte]))
            self.assertIsNotNone(self.w.pending_modbus_request)
        self.w.on_data_received(frame[-1:])
        self.assertIsNone(self.w.pending_modbus_request)
        self.assertEqual(self.w.modbus_table.item(3, 1).text(), '3')
        self.assertEqual(self.w.modbus_table.item(3, 0).text(), '速度寄存器')

    def test_noise_crc_timeout_and_polling(self):
        self.connect_fake()
        self.w.chk_modbus_poll.setChecked(True)
        self.assertTrue(self.w.modbus_poll_timer.isActive())
        self.w._poll_modbus()
        self.assertEqual(len(self.w.ser.frames), 1)
        frame = response(bytes([1, 3, 64]) + b'\x00\x01' * 32)
        self.w.on_data_received(b'noise' + frame[:-1] + bytes([frame[-1] ^ 1]) + frame)
        self.assertIsNone(self.w.pending_modbus_request)
        self.assertEqual(self.w.modbus_table.item(0, 1).text(), '1')
        self.w._poll_modbus()
        self.w._on_modbus_timeout()
        self.assertIsNone(self.w.pending_modbus_request)
        self.assertIn('超时', self.w.modbus_result.toPlainText())
        self.w.close_port()
        self.assertFalse(self.w.modbus_poll_timer.isActive())

    def test_save_reload_and_write_selection(self):
        out = self.tmp.name + '/copy.mbp'
        with patch.object(m.QFileDialog, 'getSaveFileName', return_value=(out, '')):
            self.w.on_modbus_save_profile()
        self.w._set_modbus_config({})
        with patch.object(m.QFileDialog, 'getOpenFileName', return_value=(out, '')):
            self.w.on_modbus_open_profile()
        self.assertEqual(len(self.w.modbus_entries), 32)
        self.assertEqual(self.w.spn_modbus_scan.value(), 1000)
        self.w._modbus_cell_to_write(1, 3)
        self.assertEqual(self.w.spn_modbus_addr.value(), 4017)
        self.assertEqual(self.w.cmb_modbus_func.currentData(), 6)
        self.assertEqual(self.w.edit_modbus_values.text(), '65535')

    def test_protocol_validation(self):
        request = dict(slave_id=1, function_code=3, address=4000, quantity=32)
        with self.assertRaises(ValueError):
            m.parse_modbus_rtu_response(request, response(bytes.fromhex('01 03 02 00 01')))
        with self.assertRaises(ValueError):
            m.parse_modbus_rtu_response(request, response(bytes.fromhex('01 84 02')))
        with self.assertRaisesRegex(ValueError, '从站异常'):
            m.parse_modbus_rtu_response(request, response(bytes.fromhex('01 83 02')))
        request.update(function_code=6, quantity=1, values=[7])
        with self.assertRaises(ValueError):
            m.parse_modbus_rtu_response(request, response(bytes.fromhex('01 06 0F A0 00 08')))
        self.assertEqual(m.parse_modbus_rtu_response(request, response(bytes.fromhex('01 06 0F A0 00 07')))['value'], 7)
        with self.assertRaises(ValueError):
            m.build_modbus_rtu_request(1, 3, 65535, 2)
        with self.assertRaises(ValueError):
            m.build_modbus_rtu_request(1, 5, 4000, 1, [2])


if __name__ == '__main__':
    unittest.main()
