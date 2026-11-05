"""Demo en una sola terminal: servidor HTTP + proveedor externo artificial.

Se comunican mediante peticiones HTTP reales a loopback, no con llamadas
internas del frontend. Verifica el camino utilizado por el equipo de SBC.
"""
from __future__ import annotations

import argparse
import threading
from server import make_server
from emulador_sbc import run_loop


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", default=8000, type=int)
    p.add_argument("--count", default=0, type=int, help="Envia N ventanas, luego simula desconexion")
    args = p.parse_args()
    server = make_server("127.0.0.1", args.port, "external")
    stop = threading.Event()
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    http_thread.start()
    print("===========================================================")
    print("  PULSESCOPE - DEMO DE INTEGRACION (SIN RASPBERRY NI ESP32)")
    print(f"  Abre en el navegador: http://127.0.0.1:{server.server_port}")
    print("  Ruta: Emulador -> HTTP /api/ingest -> API -> Dashboard")
    print("  Ctrl+C para salir; ninguna muestra es una medicion real")
    print("===========================================================")
    try:
        run_loop(f"http://127.0.0.1:{server.server_port}", .4, args.count, stop)
        if args.count:
            print("Emulador detenido. Observa en el navegador el aviso de datos obsoletos.")
            stop.wait()  # Permanece el servidor para comprobar la deteccion de fallo.
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        http_thread.join(timeout=2)
        print("Demo detenida.")


if __name__ == "__main__":
    main()
