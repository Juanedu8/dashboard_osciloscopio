"""Tests adicionales en Python: preset experimental y reporte del adaptador."""
import unittest
from server import Simulator, ExternalReceiver
from emulador_sbc import artificial_frame


class TestBonusAndStatus(unittest.TestCase):
    def test_bonus_40k_simulated(self):
        simulated = Simulator()
        config = simulated.set_config({"sample_rate_hz": 40000, "window_size": 512})
        frame = simulated.sample_window()
        self.assertEqual(config["sample_rate_hz"], 40000)
        self.assertEqual(frame["samples_per_channel"], 512)
        self.assertEqual(frame["dt_s"], 1/40000)

    def test_bonus_external_data(self):
        e = ExternalReceiver()
        cfg = e.set_config({"sample_rate_hz": 40000, "window_size": 64})
        result = e.ingest(artificial_frame(1, cfg))
        self.assertTrue(result["accepted"])
        self.assertEqual(e.sample_window()["sample_rate_hz"], 40000)
        self.assertFalse(e.status()["spi_connected"])

    def test_ack_report_reset_on_config(self):
        e = ExternalReceiver()
        cfg = e.config()
        e.ingest(artificial_frame(1, cfg))
        e.report_hardware({"spi_connected": True, "applied_rate_hz": 1000,
                           "applied_window_size": 512, "detail": "ESP32 ACK"})
        self.assertTrue(e.status()["spi_connected"])
        e.set_config({"sample_rate_hz": 40000})
        self.assertFalse(e.status()["spi_connected"])

    def test_report_invalid(self):
        e = ExternalReceiver()
        with self.assertRaises(ValueError):
            e.report_hardware({"spi_connected": True, "applied_rate_hz": 999,
                               "applied_window_size": 512, "detail": "invalid"})

if __name__ == "__main__":
    unittest.main()
