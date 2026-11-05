"""Prueba manual de ACK y lectura por SPI desde la Raspberry Pi; requiere hardware."""
import argparse
import time
from lector_spi import SPIReader
from protocolo_spi import NoNewWindow

p = argparse.ArgumentParser()
p.add_argument("--rate", type=int, default=1000, choices=(100, 1000, 10000, 40000))
p.add_argument("--window", type=int, default=512, choices=(64, 256, 512, 1024))
p.add_argument("--spi-hz", type=int, default=2_000_000)
p.add_argument("--ready-gpio", type=int, default=24)
p.add_argument("--count", type=int, default=10)
a = p.parse_args()
reader = SPIReader(clock_hz=a.spi_hz, ready_gpio=a.ready_gpio)
try:
    print("PING:", reader.ping())
    print("ACK config:", reader.apply_config(a.rate, a.window))
    count = 0
    start = time.monotonic()
    while count < a.count:
        try:
            ch1, ch2 = reader.read_window(a.window)
            count += 1
            print(f"ventana {count}: CH1={min(ch1):.3f}..{max(ch1):.3f}V "
                  f"CH2={min(ch2):.3f}..{max(ch2):.3f}V")
        except NoNewWindow:
            time.sleep(.02)
    duration = time.monotonic() - start
    print(f"SPI bytes= {reader.bytes_spi} | duracion= {duration:.2f}s | "
          f"transferencia observada= {reader.bytes_spi*8/duration/1e6:.3f} Mbit/s")
    print("Esto mide throughput SPI observado, NO confirma Fs fisica del ADC")
finally:
    reader.close()
