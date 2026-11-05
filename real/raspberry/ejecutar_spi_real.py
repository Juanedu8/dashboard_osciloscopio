"""Productor de muestras reales: SPI -> JSON HTTP -> dashboard SIN cambiar web/.

Ejecutar solo en Raspberry con firmware PSC1 cargado, pines verificados,
servidor Python en modo EXTERNAL y Nginx delante del dashboard.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lector_spi import SPIReader
from protocolo_spi import NoNewWindow, ProtocolError


def api(url, obj=None):
    data = json.dumps(obj).encode() if obj is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urlopen(request, timeout=3) as reply:
        return json.load(reply)


def report(base, connected, applied=None, reason=""):
    payload = {
        "spi_connected": bool(connected),
        "applied_rate_hz": applied[0] if connected and applied else None,
        "applied_window_size": applied[1] if connected and applied else None,
        "detail": str(reason)[:140],
    }
    try:
        api(base + "/api/hardware", payload)
    except (URLError, HTTPError, TimeoutError, OSError):
        pass


def main():
    parser = argparse.ArgumentParser(description="Adaptador real ESP32 SPI a PulseScope")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API LOCAL, no Nginx público")
    parser.add_argument("--bus", type=int, default=0)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--ready-gpio", type=int, default=24, help="BCM GPIO, NO número pin físico")
    parser.add_argument("--spi-hz", type=int, default=2_000_000)
    parser.add_argument("--fullscale-v", type=float, default=3.3,
                        help="Solo escala ADC provisional; medir y calibrar físicamente")
    parser.add_argument("--interval", type=float, default=0.05,
                        help="Consulta de configuración y lectura, NO es tiempo de ADC")
    parser.add_argument("--metrics", type=int, default=10, help="Segundos entre métricas de enlace")
    args = parser.parse_args()
    base = args.api.rstrip("/")
    reader = SPIReader(args.bus, args.device, args.spi_hz, args.ready_gpio, args.fullscale_v)
    sent = 0
    errors = 0
    seq_http = 0
    applied = None
    last_metrics = time.monotonic()
    last_bytes = 0
    print("[REAL] Raspberry Pi -> SPI real ESP32 -> API HTTP local; Ctrl+C para salir", flush=True)
    try:
        while True:
            try:
                config = api(base + "/api/config")
                if config.get("mode") != "external":
                    raise RuntimeError("Servidor en modo simulation. Usar --source external")
                requested = config["sample_rate_hz"], config["window_size"]
                if requested != applied:
                    # Hardware confirma el comando antes de publicar ventanas nuevas.
                    report(base, False, reason="Aplicando configuracion SPI")
                    reader.apply_config(*requested)
                    applied = requested
                    report(base, True, applied, "Comando SPI confirmado por firmware")
                    print(f"[REAL] Confirmado por ESP32 Fs={applied[0]}, N={applied[1]}", flush=True)
                a, b = reader.read_window(requested[1])
                # Si cambia la configuración durante la transferencia, descartamos la ventana.
                cfg2 = api(base + "/api/config")
                if (cfg2["sample_rate_hz"], cfg2["window_size"]) != requested:
                    continue
                seq_http += 1
                api(base + "/api/ingest", {
                    "sequence": seq_http,
                    "sample_rate_hz": requested[0],
                    "samples_per_channel": requested[1],
                    "unit": "V",
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "channel_1": a,
                    "channel_2": b,
                })
                sent += 1
                if sent % 4 == 0:
                    report(base, True, applied, "Recibiendo datos por SPI")
            except NoNewWindow:
                # Aun no hay otra ventana. Sin inventar muestras ni repetir tramas.
                pass
            except (ProtocolError, TimeoutError, OSError, HTTPError, URLError, RuntimeError) as exc:
                errors += 1
                print(f"[REAL] ERROR {type(exc).__name__}: {exc}", flush=True)
                if isinstance(exc, (ProtocolError, TimeoutError, OSError)):
                    applied = None
                    report(base, False, reason=exc)
                    time.sleep(0.5)
            if args.metrics and time.monotonic() - last_metrics >= args.metrics:
                now = time.monotonic()
                delta = now - last_metrics
                print(f"[METRICA] ventanas HTTP={sent} errores={errors} "
                      f"enlace SPI observado={(reader.bytes_spi-last_bytes)*8/delta/1000:.1f} kbit/s "
                      "(NO equivale a frecuencia ADC)", flush=True)
                last_metrics = now
                last_bytes = reader.bytes_spi
            time.sleep(max(.001, args.interval))
    except KeyboardInterrupt:
        print("[REAL] Detenido por usuario")
    finally:
        report(base, False, reason="Adaptador detenido")
        reader.close()


if __name__ == "__main__":
    main()
