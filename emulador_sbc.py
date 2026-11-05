"""Emulador de proveedor de muestras: imita al software de adquisicion del SBC.

No lee ADC ni SPI: consulta la configuracion HTTP y publica ventanas
artificiales en el MISMO endpoint que usara el adaptador SPI del equipo.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen


def call_json(url: str, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    with urlopen(Request(url, data=data, headers=headers), timeout=3) as response:
        return json.load(response)


def artificial_frame(sequence: int, config: dict) -> dict:
    """Devuelve 2 canales en voltios, estrictamente para verificar la API/UI.

    Las formas varian segun la ventana para que sean faciles de distinguir.
    NO representan temporizacion real del ESP32.
    """
    rate = config["sample_rate_hz"]
    n = config["window_size"]
    phase = sequence * .16
    a = []
    b = []
    for i in range(n):
        p = i / max(1, n - 1)
        # CH1: senoidal con cambio de fase entre ventanas.
        a.append(round(1.65 + .95 * math.sin(2 * math.pi * (3 * p) + phase), 4))
        # CH2: triangular, distinta del primer canal.
        triangle = 2 * abs(2 * ((5 * p + phase / (2 * math.pi)) % 1) - 1) - 1
        b.append(round(1.65 + .72 * triangle, 4))
    return {
        "sequence": sequence,
        "sample_rate_hz": rate,
        "samples_per_channel": n,
        "unit": "V",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "channel_1": a,
        "channel_2": b,
    }


def run_loop(base_url="http://127.0.0.1:8000", interval=.4, count=0, stop_event=None):
    """Poll de configuracion -> generador -> POST /api/ingest.

    Reemplazar generacion artificial por lectura del SPI en el adaptador real.
    """
    base = base_url.rstrip("/")
    sequence = 0
    print(f"[EMU] Conectando a {base}; emulacion externa, NO SPI real")
    while stop_event is None or not stop_event.is_set():
        if count and sequence >= count:
            print("[EMU] Finalizado. El servidor detectara que los datos quedan obsoletos.")
            break
        try:
            cfg = call_json(base + "/api/config")
            sequence += 1
            result = call_json(base + "/api/ingest", artificial_frame(sequence, cfg))
            print(f"[EMU] ventana #{result['sequence']} enviada: {cfg['window_size']} muestras/canal, Fs={cfg['sample_rate_hz']} Sa/s", flush=True)
        except Exception as exc:
            print(f"[EMU] Envio fallido: {exc} (reintentando)", flush=True)
        if stop_event is None:
            time.sleep(interval)
        else:
            stop_event.wait(interval)


def main():
    p = argparse.ArgumentParser(description="Emulador del proveedor SPI/SBC por API HTTP")
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--interval", type=float, default=.4, help="segundos entre ventanas artificiales")
    p.add_argument("--count", type=int, default=0, help="enviar N ventanas y detenerse (0=continuo)")
    args = p.parse_args()
    if not (.1 <= args.interval <= 10) or args.count < 0:
        p.error("--interval debe estar entre 0.1 y 10, --count >= 0")
    try:
        run_loop(args.url, args.interval, args.count)
    except KeyboardInterrupt:
        print("\n[EMU] Detenido")


if __name__ == "__main__":
    main()
