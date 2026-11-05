"""Contrato SPI PSC1 compartido con firmware ESP-IDF (little endian).

Dos transacciones separadas (CS se libera entre ellas):
1. CMD, 16 bytes. 2. Respuesta, 20 + 4*N bytes para GET_WINDOW,
   20 bytes para CONFIG/PING. ESP afirma GPIO READY antes de cada una.
Esta implementacion es comprobable con un transporte falso en tests.
"""
from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass

CMD_MAGIC = b"PSC0"
RESP_MAGIC = b"PSC1"
VERSION = 1
CMD_CONFIG = 1
CMD_GET_WINDOW = 2
CMD_PING = 3
STATUS_OK = 0
STATUS_NO_DATA = 1
STATUS_BAD_REQUEST = 2
STATUS_ADC_ERROR = 3
RATES = (100, 1000, 10000, 40000)
WINDOWS = (64, 256, 512, 1024)
CMD_FMT = "<4sBBHII"          # 16 bytes
RESP_FMT = "<4sBBHIIHH"       # 20 bytes
CMD_BYTES = struct.calcsize(CMD_FMT)
RESP_BYTES = struct.calcsize(RESP_FMT)


class ProtocolError(Exception):
    pass


class NoNewWindow(Exception):
    pass


@dataclass(frozen=True)
class Packet:
    status: int
    sample_rate_hz: int
    window_size: int
    sequence: int
    raw_1: tuple[int, ...]
    raw_2: tuple[int, ...]


def command(cmd: int, sample_rate_hz: int = 0, window_size: int = 0) -> bytes:
    if cmd not in (CMD_CONFIG, CMD_GET_WINDOW, CMD_PING):
        raise ValueError("Comando no reconocido")
    if cmd == CMD_CONFIG and (sample_rate_hz not in RATES or window_size not in WINDOWS):
        raise ValueError("Preset o ventana no permitida")
    return struct.pack(CMD_FMT, CMD_MAGIC, VERSION, cmd, window_size, sample_rate_hz, 0)


def frame_size(window_size: int) -> int:
    if window_size not in WINDOWS:
        raise ValueError("Tamaño de ventana no permitido")
    return RESP_BYTES + (4 * window_size)


def parse_response(data: bytes, expected_n: int | None = None) -> Packet:
    if len(data) < RESP_BYTES:
        raise ProtocolError("Respuesta SPI demasiado corta")
    magic, version, status, n, rate, sequence, received_crc, reserved = struct.unpack_from(RESP_FMT, data)
    if magic != RESP_MAGIC or version != VERSION or reserved != 0:
        raise ProtocolError("Cabecera SPI invalida")
    if status not in (STATUS_OK, STATUS_NO_DATA, STATUS_BAD_REQUEST, STATUS_ADC_ERROR):
        raise ProtocolError("Estado SPI invalido")
    if expected_n is not None and n != expected_n:
        raise ProtocolError(f"Ventana SPI inesperada: {n} != {expected_n}")
    wanted = RESP_BYTES + (4 * n) if expected_n is not None else RESP_BYTES
    if len(data) != wanted:
        raise ProtocolError(f"Longitud SPI: {len(data)} != {wanted}")
    crc = binascii.crc_hqx(data[:16] + data[RESP_BYTES:], 0xFFFF)
    if received_crc != crc:
        raise ProtocolError(f"CRC SPI incorrecto: {received_crc:04x} != {crc:04x}")
    if status != STATUS_OK:
        if status == STATUS_NO_DATA:
            raise NoNewWindow("El ESP32 aun no completo una ventana nueva")
        raise ProtocolError(f"Firmware ESP32 devolvio estado de error {status}")
    if expected_n is None:
        return Packet(status, rate, n, sequence, (), ())
    if rate not in RATES:
        raise ProtocolError("Frecuencia de firmware inesperada")
    values = struct.unpack_from("<" + "H" * (n * 2), data, RESP_BYTES)
    if any(v > 4095 for v in values):
        raise ProtocolError("Dato ADC fuera de rango de 12 bits")
    return Packet(status, rate, n, sequence, values[0::2], values[1::2])


def make_response(*, rate=1000, n=64, seq=1, status=STATUS_OK,
                  a=None, b=None, data_response=True) -> bytes:
    """Solo pruebas unitarias del contrato, NO mide hardware real."""
    payload = b""
    if data_response:
        a = [2048] * n if a is None else a
        b = [1024] * n if b is None else b
        payload = struct.pack("<" + "H" * (2 * n), *(v for ab in zip(a, b) for v in ab))
    header = struct.pack(RESP_FMT, RESP_MAGIC, VERSION, status, n, rate, seq, 0, 0)
    crc = binascii.crc_hqx(header[:16] + payload, 0xFFFF)
    return header[:16] + struct.pack("<H", crc) + header[18:] + payload
