"""Pruebas de contrato entre dashboard y proveedor externo artificial."""
import json
import sys
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import make_server
from emulador_sbc import artificial_frame, run_loop
import threading


class ExternalIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.http = make_server("127.0.0.1", 0, "external")
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)

    def get(self, path):
        with urlopen(self.url + path, timeout=3) as response:
            return json.load(response)

    def post(self, path, obj):
        request = Request(self.url + path, data=json.dumps(obj).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def test_initially_no_samples_and_status(self):
        self.assertEqual(self.get("/api/config")["mode"], "external")
        self.assertFalse(self.get("/api/estado")["ingest_connected"])
        with self.assertRaises(HTTPError) as err:
            self.get("/api/muestras")
        self.assertEqual(err.exception.code, 503)

    def test_end_to_end_input_to_dashboard_output(self):
        cfg = self.post("/api/config", {"sample_rate_hz": 10000, "window_size": 64, "refresh_interval_s": 2})
        frame = artificial_frame(1, cfg)
        ok = self.post("/api/ingest", frame)
        self.assertTrue(ok["accepted"])
        output = self.get("/api/muestras")
        self.assertEqual(output["mode"], "external")
        self.assertEqual(output["sequence"], 1)
        self.assertEqual(output["channel_1"], frame["channel_1"])
        self.assertEqual(output["channel_2"], frame["channel_2"])
        self.assertEqual(output["samples_per_channel"], 64)
        self.assertEqual(output["dt_s"], 1/10000)
        self.assertTrue(self.get("/api/estado")["ingest_connected"])
        self.assertEqual(self.get("/api/estado")["frames_received"], 1)
        self.assertFalse(self.get("/api/estado")["spi_connected"])

    def test_rejects_bad_frames_and_duplicate_sequences(self):
        cfg = self.post("/api/config", {"window_size": 64})
        frame = artificial_frame(1, cfg)
        self.post("/api/ingest", frame)
        invalid = [
            frame,  # ventana duplicada
            {**artificial_frame(2, cfg), "channel_2": [1.0] * 63},
            {**artificial_frame(2, cfg), "channel_1": [float("nan")] * 64},
            {**artificial_frame(2, cfg), "sample_rate_hz": 10000},
            {**artificial_frame(2, cfg), "channel_1": [4.5] * 64},
        ]
        for item in invalid:
            with self.subTest(item=str(item.keys())):
                with self.assertRaises(HTTPError) as err:
                    self.post("/api/ingest", item)
                self.assertEqual(err.exception.code, 400)

    def test_change_configuration_requires_new_matching_frame(self):
        cfg = self.post("/api/config", {"window_size": 64})
        self.post("/api/ingest", artificial_frame(1, cfg))
        self.post("/api/config", {"window_size": 256})
        with self.assertRaises(HTTPError) as err:
            self.get("/api/muestras")
        self.assertEqual(err.exception.code, 503)
        cfg = self.get("/api/config")
        self.post("/api/ingest", artificial_frame(2, cfg))
        self.assertEqual(len(self.get("/api/muestras")["channel_1"]), 256)

    def test_stale_data_is_not_presented_as_live(self):
        cfg = self.post("/api/config", {"window_size": 64})
        self.post("/api/ingest", artificial_frame(1, cfg))
        provider = self.http.RequestHandlerClass.func.simulator
        with provider.lock:
            provider.last_received_at -= 100
        with self.assertRaises(HTTPError) as err:
            self.get("/api/muestras")
        self.assertEqual(err.exception.code, 503)
        self.assertFalse(self.get("/api/estado")["ingest_connected"])

    def test_emulator_sends_real_http_frames(self):
        self.post("/api/config", {"window_size": 64, "sample_rate_hz": 100})
        run_loop(self.url, interval=.1, count=2)
        state = self.get("/api/estado")
        self.assertEqual(state["frames_received"], 2)
        self.assertEqual(self.get("/api/muestras")["sequence"], 2)


if __name__ == "__main__":
    unittest.main()
