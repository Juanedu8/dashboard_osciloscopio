"""Servidor HTTP local para el proyecto 2 de adquisicion (solo stdlib).

Ahora genera muestras SIMULADAS para poder desarrollar el dashboard sin SBC.
En la integracion, sustituir Simulator.sample_window por el lector SPI real.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "web"
VALID_RATES = (100, 1000, 10000, 40000)
VALID_WINDOWS = (64, 256, 512, 1024)
VALID_REFRESH = (1, 2, 4)


class Simulator:
    """Contrato de datos equivalente al que implementara la recepcion SPI."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sample_rate_hz = 1000
        self.window_size = 512
        self.refresh_interval_s = 1
        self.sequence = 0

    def config(self) -> dict:
        with self.lock:
            return {
                "sample_rate_hz": self.sample_rate_hz,
                "window_size": self.window_size,
                "refresh_interval_s": self.refresh_interval_s,
                "mode": "simulation",
            }

    def set_config(self, values: dict) -> dict:
        if not isinstance(values, dict):
            raise ValueError("El cuerpo JSON debe ser un objeto")
        options = {
            "sample_rate_hz": VALID_RATES,
            "window_size": VALID_WINDOWS,
            "refresh_interval_s": VALID_REFRESH,
        }
        unexpected = set(values) - set(options)
        if unexpected:
            raise ValueError("Campo(s) no permitido(s): " + ", ".join(sorted(unexpected)))
        if not values:
            raise ValueError("Se requiere al menos un campo de configuracion")
        # bool debe rechazarse; en Python es una subclase de int.
        for key, value in values.items():
            if type(value) is not int or value not in options[key]:
                raise ValueError(f"{key}: valores permitidos {list(options[key])}")
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)
        return self.config()

    def sample_window(self) -> dict:
        with self.lock:
            self.sequence += 1
            sequence = self.sequence
            rate = self.sample_rate_hz
            n = self.window_size
        rng = random.Random(1947 + sequence)
        phase = sequence * 0.22
        ch1 = []
        ch2 = []
        for i in range(n):
            # Los ciclos dependen del tamano de ventana SOLO para la demo visual.
            # No se afirma que sean mediciones fisicas reales.
            p = i / n
            sine = 1.65 + 0.96 * math.sin(2 * math.pi * 4 * p + phase)
            sine += 0.10 * math.sin(2 * math.pi * 12 * p + phase * 0.3)
            sine += rng.uniform(-0.022, 0.022)
            wave = 1.65 + 0.66 * math.sin(2 * math.pi * 7 * p + phase * 0.66)
            wave += 0.21 * math.sin(2 * math.pi * 14 * p + 0.8)
            wave += rng.uniform(-0.03, 0.03)
            ch1.append(round(max(0.0, min(3.3, sine)), 4))
            ch2.append(round(max(0.0, min(3.3, wave)), 4))
        return {
            "mode": "simulation",
            "sequence": sequence,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "sample_rate_hz": rate,
            "dt_s": 1 / rate,
            "samples_per_channel": n,
            "channel_count": 2,
            "unit": "V",
            "channel_1": ch1,
            "channel_2": ch2,
        }


class ExternalReceiver(Simulator):
    """Recibe ventanas por HTTP desde un adaptador SBC (aqui, un emulador).

    La web mantiene el mismo GET /api/muestras para ambos proveedores.
    NO prueba por si solo la comunicacion SPI ni el muestreo fisico.
    """

    def __init__(self):
        super().__init__()
        self.last_window = None
        self.last_received_at = None
        self.frames_received = 0
        self.hardware_report = None
        self.hardware_report_at = None

    def config(self) -> dict:
        result = super().config()
        result["mode"] = "external"
        return result

    def sample_window(self) -> dict | None:
        with self.lock:
            if self.last_window is None or self.last_received_at is None:
                return None
            # Evita mostrar capturas antiguas como si fueran nuevas.
            stale_after = max(2, 2 * self.refresh_interval_s)
            if time.monotonic() - self.last_received_at > stale_after:
                return None
            if (self.last_window["sample_rate_hz"] != self.sample_rate_hz or
                    self.last_window["samples_per_channel"] != self.window_size):
                return None
            return dict(self.last_window)

    def report_hardware(self, data: dict) -> dict:
        """Estado reportado por el adaptador LOCAL del SBC (no es prueba fisica de Fs)."""
        if not isinstance(data, dict) or set(data) != {
            "spi_connected", "applied_rate_hz", "applied_window_size", "detail"
        }:
            raise ValueError("Campos de telemetria invalidos")
        connected = data["spi_connected"]
        rate, n, detail = data["applied_rate_hz"], data["applied_window_size"], data["detail"]
        if type(connected) is not bool or not isinstance(detail, str) or len(detail) > 140:
            raise ValueError("Telemetria invalida")
        if connected and (type(rate) is not int or rate not in VALID_RATES or
                          type(n) is not int or n not in VALID_WINDOWS):
            raise ValueError("Preset confirmado invalido")
        if not connected and (rate is not None or n is not None):
            raise ValueError("Desconectado no puede confirmar preset")
        with self.lock:
            self.hardware_report = dict(data)
            self.hardware_report_at = time.monotonic()
        return {"accepted": True}

    def set_config(self, values: dict) -> dict:
        previous = (self.sample_rate_hz, self.window_size)
        result = super().set_config(values)
        if previous != (result["sample_rate_hz"], result["window_size"]):
            with self.lock:
                self.hardware_report = None  # Nunca fingir ACK de un preset nuevo.
                self.hardware_report_at = None
        return result

    def status(self) -> dict:
        with self.lock:
            age = None if self.last_received_at is None else round(time.monotonic() - self.last_received_at, 2)
            alive = age is not None and age <= max(2, 2 * self.refresh_interval_s)
            hw_alive = (self.hardware_report is not None and self.hardware_report_at is not None
                        and time.monotonic() - self.hardware_report_at < 6)
            report = self.hardware_report if hw_alive else None
            match = (report is not None and report["applied_rate_hz"] == self.sample_rate_hz
                     and report["applied_window_size"] == self.window_size)
            spi_ok = bool(report and report["spi_connected"] and match and alive)
            return {
                "ok": True, "mode": "external",
                "source": "SPI ESP32 reportado por SBC" if spi_ok else "Proveedor HTTP externo (SPI aun no confirmado)",
                "channels": 2, "ingest_connected": alive,
                "frames_received": self.frames_received, "last_frame_age_s": age,
                "spi_connected": spi_ok, "sbc_connected": bool(hw_alive),
                "applied_rate_hz": report["applied_rate_hz"] if spi_ok else None,
                "applied_window_size": report["applied_window_size"] if spi_ok else None,
                "hardware_detail": report["detail"] if report else "Sin reporte reciente",
                "sampling_physically_verified": False,
            }

    def ingest(self, frame: dict) -> dict:
        if not isinstance(frame, dict):
            raise ValueError("Se esperaba un objeto JSON")
        required = {"sequence", "sample_rate_hz", "channel_1", "channel_2"}
        allowed = required | {"generated_at_utc", "samples_per_channel", "unit"}
        if not required <= set(frame) or set(frame) - allowed:
            raise ValueError("Trama incompleta o con campos desconocidos")
        rate, seq, ch1, ch2 = (frame[k] for k in ("sample_rate_hz", "sequence", "channel_1", "channel_2"))
        if type(rate) is not int or type(seq) is not int or seq < 1:
            raise ValueError("sample_rate_hz y sequence deben ser enteros validos")
        if not isinstance(ch1, list) or not isinstance(ch2, list):
            raise ValueError("channel_1 y channel_2 deben ser listas")
        n = len(ch1)
        if n < 64 or n > 1024 or len(ch2) != n:
            raise ValueError("Ambos canales deben tener igual longitud entre 64 y 1024")
        if "samples_per_channel" in frame and (type(frame["samples_per_channel"]) is not int or frame["samples_per_channel"] != n):
            raise ValueError("samples_per_channel no coincide con los canales")
        unit = frame.get("unit", "V")
        if unit != "V":
            raise ValueError("Por ahora la API solo acepta muestras en voltios (V)")
        for samples in (ch1, ch2):
            if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 3.3 for v in samples):
                raise ValueError("Los valores deben ser voltajes finitos de 0 a 3,3 V")
        stamp = frame.get("generated_at_utc")
        if stamp is None:
            stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        else:
            if not isinstance(stamp, str) or len(stamp) > 45:
                raise ValueError("generated_at_utc debe ser ISO 8601")
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Se requiere zona horaria UTC")
            except ValueError as e:
                raise ValueError("generated_at_utc debe ser ISO 8601 con zona horaria") from e
        with self.lock:
            if rate != self.sample_rate_hz or n != self.window_size:
                raise ValueError("Trama incompatible con /api/config; consultar configuracion")
            if self.last_window and seq <= self.last_window["sequence"]:
                raise ValueError("sequence debe aumentar en cada ventana (sin duplicados)")
            self.last_window = {
                "mode": "external", "sequence": seq,
                "generated_at_utc": stamp,
                "sample_rate_hz": rate, "dt_s": 1 / rate,
                "samples_per_channel": n, "channel_count": 2,
                "unit": "V", "channel_1": list(ch1), "channel_2": list(ch2),
            }
            self.last_received_at = time.monotonic()
            self.frames_received += 1
            return {"accepted": True, "sequence": seq, "frames_received": self.frames_received}


class AppHandler(SimpleHTTPRequestHandler):
    simulator: Simulator

    def log_message(self, fmt: str, *args) -> None:
        print(f"[HTTP] {self.address_string()} - {fmt % args}")

    def respond_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        # urlsplit evita que los query strings interfieran con los endpoints.
        from urllib.parse import urlsplit
        path = urlsplit(self.path).path
        if path == "/api/muestras":
            frame = self.simulator.sample_window()
            if frame is None:
                self.respond_json(503, {"error": "Esperando una ventana reciente del proveedor externo"})
            else:
                self.respond_json(200, frame)
        elif path == "/api/config":
            self.respond_json(200, self.simulator.config())
        elif path == "/api/estado":
            if isinstance(self.simulator, ExternalReceiver):
                self.respond_json(200, self.simulator.status())
            else:
                self.respond_json(200, {
                    "ok": True,
                    "mode": "simulation",
                    "source": "datos simulados (sin ADC ni SPI)",
                    "channels": 2,
                    "spi_connected": False,
                    "sbc_connected": False,
                })
        else:
            super().do_GET()

    def do_POST(self) -> None:
        from urllib.parse import urlsplit
        path = urlsplit(self.path).path
        if path not in ("/api/config", "/api/ingest", "/api/hardware"):
            self.respond_json(404, {"error": "Endpoint no encontrado"})
            return
        if path in ("/api/ingest", "/api/hardware") and not isinstance(self.simulator, ExternalReceiver):
            self.respond_json(409, {"error": "Iniciar servidor con --source external"})
            return
        try:
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise ValueError("Content-Type debe ser application/json")
            size = int(self.headers.get("Content-Length", "0"))
            if not (1 <= size <= (131072 if path == "/api/ingest" else 2048)):
                raise ValueError("Tamano JSON no valido")
            data = json.loads(self.rfile.read(size))
            if path == "/api/config":
                result = self.simulator.set_config(data)
            elif path == "/api/hardware":
                result = self.simulator.report_hardware(data)
            else:
                result = self.simulator.ingest(data)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.respond_json(400, {"error": str(exc)})
            return
        self.respond_json(200, result)


def make_server(host="127.0.0.1", port=8000, source="simulation"):
    provider = Simulator() if source == "simulation" else ExternalReceiver()
    handler = type("DashboardHandler", (AppHandler,), {"simulator": provider})
    return ThreadingHTTPServer((host, port), partial(handler, directory=str(ROOT)))


def main():
    parser = argparse.ArgumentParser(description="Dashboard de adquisicion, modo simulacion")
    parser.add_argument("--host", default="127.0.0.1", help="Interfaz (por defecto: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP (por defecto: 8000)")
    parser.add_argument("--source", choices=("simulation", "external"), default="simulation",
                        help="simulation: generacion interna; external: POST /api/ingest")
    args = parser.parse_args()
    server = make_server(args.host, args.port, args.source)
    print(f"Dashboard activo: http://{args.host}:{args.port}")
    print(f"FUENTE: {args.source}. Ningun modo simulado verifica ADC ni SPI.")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
