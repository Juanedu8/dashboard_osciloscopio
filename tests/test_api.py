"""Pruebas unitarias de la API de simulacion (sin dependencias externas)."""
import json
import sys
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import AppHandler, ROOT, Simulator


class APITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = type("TestHandler", (AppHandler,), {"simulator": Simulator(), "log_message": lambda *args: None})
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(ROOT)))
        cls.url = f"http://127.0.0.1:{cls.http.server_port}"
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=2)

    def get(self, path):
        with urlopen(self.url + path, timeout=2) as r:
            return json.load(r)

    def post(self, body):
        request = Request(self.url + "/api/config", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=2) as r:
            return json.load(r)

    def test_a_initial_defaults_and_status(self):
        self.assertEqual(self.get("/api/config")["sample_rate_hz"], 1000)
        self.assertFalse(self.get("/api/estado")["spi_connected"])

    def test_configurable_rates_and_window(self):
        for rate in (100, 1000, 10000):
            result = self.post({"sample_rate_hz": rate, "window_size": 64})
            self.assertEqual(result["sample_rate_hz"], rate)
            data = self.get("/api/muestras")
            self.assertEqual(data["dt_s"], 1 / rate)
            self.assertEqual(len(data["channel_1"]), 64)
            self.assertEqual(len(data["channel_2"]), 64)
            self.assertTrue(all(0 <= v <= 3.3 for v in data["channel_1"] + data["channel_2"]))

    def test_window_sizes_and_refresh(self):
        for size in (64, 256, 512, 1024):
            self.post({"window_size": size})
            self.assertEqual(len(self.get("/api/muestras")["channel_1"]), size)
        for t in (1, 2, 4):
            self.assertEqual(self.post({"refresh_interval_s": t})["refresh_interval_s"], t)

    def test_bad_config_is_rejected(self):
        for body in ({"sample_rate_hz": 42000}, {"window_size": 32}, {"refresh_interval_s": 0}, {"unknown": 1}, {"sample_rate_hz": True}, {}):
            with self.assertRaises(HTTPError) as err:
                self.post(body)
            self.assertEqual(err.exception.code, 400)

    def test_static_web(self):
        with urlopen(self.url + "/", timeout=2) as response:
            html = response.read().decode()
        self.assertIn("Osciloscopio", html)
        with urlopen(self.url + "/app.js", timeout=2) as response:
            self.assertIn("function plot", response.read().decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
