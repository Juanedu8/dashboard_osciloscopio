"""SPI REAL para Raspberry Pi Zero 2 W <-> ESP32 (ESP-IDF).

NO arrancar hasta comprobar pinout y conexion fisica. Maestra SPI0 en
Raspberry, ESP32 esclavo. GPIO READY adicional evita desincronizacion.
"""
from __future__ import annotations

import time
from protocolo_spi import (CMD_CONFIG, CMD_GET_WINDOW, CMD_PING, RESP_BYTES,
                           ProtocolError, NoNewWindow, command, frame_size,
                           parse_response)


class SPIReader:
    def __init__(self, bus=0, device=0, clock_hz=2_000_000, ready_gpio=24,
                 voltage_fullscale=3.3, timeout_s=2.0, spi=None, gpio=None):
        if not 1 <= clock_hz <= 5_000_000:
            raise ValueError("Probar un reloj entre 1 y 5 MHz; no asumir limite real")
        if not (0 < voltage_fullscale <= 3.3):
            raise ValueError("Escala ADC provisional debe ser <= 3.3 V")
        if spi is None:
            import spidev
            spi = spidev.SpiDev()
            spi.open(bus, device)
        if gpio is None:
            import RPi.GPIO as gpio
            gpio.setwarnings(False)
            gpio.setmode(gpio.BCM)
            gpio.setup(ready_gpio, gpio.IN, pull_up_down=gpio.PUD_DOWN)
        self.spi = spi
        self.gpio = gpio
        self.ready_gpio = ready_gpio
        self.timeout = timeout_s
        self.vref = voltage_fullscale
        self.spi.mode = 0
        self.spi.max_speed_hz = clock_hz
        self.spi.bits_per_word = 8
        self.last_esp_seq = -1
        self.confirmed = None
        self.bytes_spi = 0
        self.start = time.monotonic()

    def _wait_level(self, level: int):
        cutoff = time.monotonic() + self.timeout
        while self.gpio.input(self.ready_gpio) != level:
            if time.monotonic() > cutoff:
                raise TimeoutError(f"Timeout esperando READY={level}; revisar pines, firmware y tierra")
            time.sleep(.0001)

    def _transfer(self, request: bytes) -> bytes:
        result = bytes(self.spi.xfer2(list(request)))
        if len(result) != len(request):
            raise ProtocolError("SPI devolvio cantidad de bytes diferente")
        self.bytes_spi += len(request)
        return result

    def _exchange(self, cmd: bytes, response_n: int) -> bytes:
        self._wait_level(1)           # El ESP32 preparo transaccion de comando.
        self._transfer(cmd)
        self._wait_level(0)           # ESP32 consumio comando, READY en 0.
        self._wait_level(1)           # ESP32 preparo respuesta nueva.
        out = self._transfer(bytes(response_n))
        self._wait_level(0)
        return out

    def ping(self):
        return parse_response(self._exchange(command(CMD_PING), RESP_BYTES))

    def apply_config(self, rate, n):
        data = self._exchange(command(CMD_CONFIG, rate, n), RESP_BYTES)
        ack = parse_response(data)
        if ack.sample_rate_hz != rate or ack.window_size != n:
            raise ProtocolError("El ACK del ESP32 no coincide con la configuracion pedida")
        self.confirmed = (rate, n)
        self.last_esp_seq = -1
        return ack

    def read_window(self, n):
        if self.confirmed is None or self.confirmed[1] != n:
            raise ProtocolError("Primero confirmar configuracion por SPI")
        response = self._exchange(command(CMD_GET_WINDOW), frame_size(n))
        packet = parse_response(response, expected_n=n)
        if packet.sample_rate_hz != self.confirmed[0]:
            raise ProtocolError("Fs reportada por uC distinta de la configurada")
        if packet.sequence <= self.last_esp_seq:
            raise NoNewWindow("Ventana ya recibida antes")
        self.last_esp_seq = packet.sequence
        # APROXIMACION SIN CALIBRAR. Cambiar escala por calibracion real de ADC.
        k = self.vref / 4095.0
        return ([round(x * k, 4) for x in packet.raw_1],
                [round(x * k, 4) for x in packet.raw_2])

    def close(self):
        close = getattr(self.spi, "close", None)
        if callable(close):
            close()
        # No GPIO.cleanup global: otro servicio podria usar GPIO.
