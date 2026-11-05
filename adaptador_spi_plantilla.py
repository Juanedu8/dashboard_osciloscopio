"""PLANTILLA DE INTEGRACION (NO IMPLEMENTA SPI FISICO).

Quien programe la Raspberry Pi implementa solo dos metodos en `SPIHardware`:
1) apply_config: envia por SPI los presets al ESP32 y valida respuesta.
2) read_window: lee una ventana binaria SPI, verifica su integridad,
   convierte el ADC a V y devuelve dos listas de flotantes.

El resto del codigo ya usa el mismo contrato HTTP que la demo.

Requisitos: servidor iniciado con `python server.py --source external`.
ATENCION: no se pueden fijar pines, velocidad SPI, CS o trama binaria
sin concretar la placa Raspberry, conexiones y protocolo con el grupo.
"""
from __future__ import annotations

import time
from emulador_sbc import call_json


class SPIHardware:
    def apply_config(self, sample_rate_hz: int, window_size: int):
        """TODO uC+SPI: configurar ADC y devolver solo tras confirmacion del ESP32."""
        raise NotImplementedError("Falta implementar comando SPI + ACK desde firmware")

    def read_window(self, window_size: int) -> tuple[list[float], list[float]]:
        """TODO SPI: leer N muestras de cada canal, ya convertidas a voltios."""
        raise NotImplementedError("Falta implementar transferencia SPI y conversion ADC a V")


def run_adapter(device: SPIHardware, url="http://127.0.0.1:8000"):
    """Lazo de adquisicion HTTP del SBC (solo funciona al implementar SPIHardware)."""
    url = url.rstrip("/")
    last_setting = None
    sequence = 0
    while True:
        config = call_json(url + "/api/config")
        setting = (config["sample_rate_hz"], config["window_size"])
        if setting != last_setting:
            # La configuracion de SPI depende del hardware. No inventamos ACK.
            device.apply_config(*setting)
            last_setting = setting
        a, b = device.read_window(config["window_size"])
        sequence += 1
        payload = {
            "sequence": sequence,
            "sample_rate_hz": setting[0],
            "samples_per_channel": setting[1],
            "unit": "V",
            "channel_1": a,
            "channel_2": b,
        }
        call_json(url + "/api/ingest", payload)
        # El intervalo de dashboard es independiente del tiempo de muestreo.
        # El lazo real debe usar bloqueo/ready por SPI, no asumir que este sleep mide el ADC.
        time.sleep(.05)


if __name__ == "__main__":
    print("Esta es una PLANTILLA: implemente SPIHardware con su protocolo y hardware.")
    print("Para pruebas sin SBC ejecute: python demo_integracion.py")
