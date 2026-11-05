"""No acceden a SPI/ADC fisicos; prueban contrato y verificador de CRC."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raspberry"))
from protocolo_spi import (CMD_CONFIG, CMD_GET_WINDOW, NoNewWindow, ProtocolError,
                           STATUS_NO_DATA, command, frame_size, make_response,
                           parse_response)
from lector_spi import SPIReader


class FakeGPIO:
    BCM = 11
    IN = 1
    PUD_DOWN = 0

    def __init__(self):
        self.signal = 1
        self.queue = []

    def input(self, pin):
        if self.queue:
            self.signal = self.queue.pop(0)
        return self.signal


class FakeSPI:
    def __init__(self, gpio):
        self.gpio = gpio
        self.spi_mode = 0
        self.seq = 0
        self.rate = 1000
        self.n = 64
        self.transfers = 0

    def xfer2(self, request):
        self.transfers += 1
        if len(request) == 16:
            data = bytes(request)
            if data[5] == CMD_CONFIG:
                self.n = int.from_bytes(data[6:8], "little")
                self.rate = int.from_bytes(data[8:12], "little")
            self.action = data[5]
            self.gpio.queue = [0, 1]  # READY transitions after CMD
            return [0] * len(request)
        self.gpio.queue = [0, 1]  # ready LOW for reply end, HIGH for next cmd
        if self.action == CMD_CONFIG:
            return list(make_response(rate=self.rate, n=self.n, data_response=False))
        self.seq += 1
        return list(make_response(rate=self.rate, n=self.n, seq=self.seq))


class TestProtocol(unittest.TestCase):
    def test_command_binary_header(self):
        raw = command(CMD_CONFIG, 40000, 1024)
        self.assertEqual(len(raw), 16)
        self.assertEqual(raw[:4], b"PSC0")
        self.assertEqual(int.from_bytes(raw[8:12], "little"), 40000)

    def test_40k_two_channels_and_crc(self):
        a = [i % 4096 for i in range(512)]
        b = [4095 - i for i in range(512)]
        frame = make_response(rate=40000, n=512, a=a, b=b)
        self.assertEqual(len(frame), frame_size(512))
        parsed = parse_response(frame, expected_n=512)
        self.assertEqual(parsed.raw_1, tuple(a))
        self.assertEqual(parsed.raw_2, tuple(b))

    def test_tampered_crc_fails(self):
        data = bytearray(make_response(rate=40000, n=64))
        data[-1] ^= 0x80
        with self.assertRaises(ProtocolError):
            parse_response(bytes(data), expected_n=64)

    def test_no_data(self):
        data = make_response(rate=1000, n=64, status=STATUS_NO_DATA)
        with self.assertRaises(NoNewWindow):
            parse_response(data, expected_n=64)

    def test_spi_reader_fake_config_then_data(self):
        gpio = FakeGPIO()
        spi = FakeSPI(gpio)
        reader = SPIReader(spi=spi, gpio=gpio, ready_gpio=24)
        reader.apply_config(40000, 64)
        ch1, ch2 = reader.read_window(64)
        self.assertEqual(len(ch1), 64)
        self.assertEqual(len(ch2), 64)
        self.assertEqual(reader.confirmed, (40000, 64))
        self.assertEqual(spi.transfers, 4)


if __name__ == "__main__":
    unittest.main()
