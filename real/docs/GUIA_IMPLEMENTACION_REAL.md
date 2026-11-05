# Integración física PulseScope: ESP32 + Raspberry Pi Zero 2 W

**Estado:** código de referencia de integración **listo para compilar y llevar al laboratorio**, pero todavía **SIN validar en vuestro hardware**. El modelo M5Stack concreto no se conoce. No debe afirmarse que los pines propuestos estén disponibles ni que 40.000 Sa/s estén logrados sin pruebas físicas.

## Qué se conserva

Se mantiene el frontend original `web/`, el backend `server.py`, `PRUEBA_SIN_RASPBERRY.bat`, `demo_integracion.py` y el emulador. Se agrega **40.000 Sa/s (experimental)** al selector/validador y un indicador de enlace SPI reportado (no es prueba de exactitud temporal). La API HTTP/JSON original **no cambia**: las ventanas entran a `POST /api/ingest` y las gráficas consultan `GET /api/muestras`.

## 0. Antes de cablear: identificar modelo M5

La hoja de datos del chip ESP32-D0WDQ6 **no permite deducir el pinout de un M5Stack montado**. Los GPIO incluidos en `real/esp32_idf/main/main.c` son **valores de ejemplo**. Algunos GPIO utilizados por la pantalla y otros periféricos de M5Stack pueden estar ocupados.

**No conectar hasta comprobar:** modelo comercial de la M5, esquemático de esa placa, disponibilidad de dos entradas **ADC1**, cinco GPIO libres para SPI/READY, alimentación y masa compartida. GPIO34/GPIO35 son entradas ADC1 del ESP32 clásico, **pero podrían no estar expuestas** en la M5 concreta. El firmware usa por defecto `ADC_CHANNEL_6` y `ADC_CHANNEL_7`; si son inaccesibles hay que cambiar canales y circuito de prueba. **No aplicar 5 V ni voltaje negativo a los GPIO**. Las señales del generador deben quedar dentro del rango admitido por el ADC y, si hace falta, pasar por un acondicionamiento adecuado. La referencia 3,3 V del backend es una conversión provisional, no calibración.

### Cableado propuesto, a CONVALIDAR con esquemático M5

| Raspberry Pi Zero 2 W, **BCM** | Pin físico de 40 pines | Señal | ESP32 **EJEMPLO**, adaptar |
|---|---:|---|---|
| GPIO10 | 19 | MOSI | GPIO23 |
| GPIO9 | 21 | MISO | GPIO19 |
| GPIO11 | 23 | SCLK | GPIO18 |
| GPIO8 | 24 | CE0/CS | GPIO5 (**pin de arranque; verificar**) |
| GPIO24 | 18 | READY **entrada** | GPIO27 **salida**, verificar |
| GND | 6 (o cualquier GND) | Masa compartida | GND |

Tensiones lógicas **3,3 V**. Conectar correctamente GND. No unir las alimentaciones 5V ni 3V3 de ambos equipos sin un diseño de potencia. Usar cables cortos, verificar orden MOSI/MISO/SCLK/CS y no confundir **BCM** con número físico.

## 1. Cargar firmware en el ESP32 (integrante firmware)

Requiere **ESP-IDF 5.5** y herramientas ESP-IDF operativas (no está incluido ESP-IDF en el ZIP). Desde `dashboard_osciloscopio/real/esp32_idf`:

```bash
idf.py set-target esp32
idf.py build
idf.py -p PUERTO_DEL_ESP32 flash monitor
```

Ejemplo Windows ESP-IDF PowerShell: `idf.py -p COM5 flash monitor`; el puerto varía. Antes de compilar, **cambiar los cinco `PS_SPI_*_GPIO/PS_READY_GPIO` y los dos `PS_ADC_CH*`** de `main/main.c` a pines reales comprobados en la M5.

El firmware hace ADC1 continuo + DMA para dos canales; la tasa del motor de conversiones es **total entre los dos canales**, no por canal: 20.000 conversiones/s totales para las tres tasas base y 80.000 conversiones/s totales para 40.000 Sa/s **por canal**. Las tasas menores usan selección 1 de cada 10 o 100 muestras. Un buffer circular permite actualizar la ventana después del llenado inicial sin esperar un nuevo bloque de tamaño N completo.

La consola del ESP32 imprime cada ~5 s `METRIC target=...; counted CH1=... CH2=...`. Esta es una **estimación de software**; la uniformidad temporal de la adquisición debe verificarse experimentalmente.

## 2. Preparar Raspberry Pi (integrante SBC)

Usar Raspberry Pi OS con acceso a red y terminal; necesitarás `sudo`. Habilitar SPI mediante:

```bash
sudo raspi-config
# Interface Options -> SPI -> Enable
sudo reboot
ls /dev/spidev0.0
```

Entra en la carpeta `dashboard_osciloscopio` que se copió a la Raspberry; instalar con:

```bash
sudo bash real/deploy/preparar_servicios.sh
```

El script instala Nginx, `python3-spidev` y `python3-rpi.gpio`, copia el proyecto a `/opt/dashboard_osciloscopio`, habilita el backend Python **modo external** solo en localhost, y publica los archivos de `web/` con **Nginx en el puerto 80**. **No arranca SPI automáticamente** hasta que se verifiquen conexiones.

Si se usan rutas o usuarios diferentes, adaptar los archivos de `real/deploy/`. El script asume nombres de paquetes disponibles en la versión de Raspberry Pi OS; si el sistema no tiene `python3-rpi.gpio`, instalar una alternativa compatible después de adaptar el lector GPIO. Se usan GPIO BCM y SPI0 CE0. El servicio ejecuta Python del sistema, por lo que hay que instalar los paquetes en ese entorno.

## 3. Probar SPI físicamente ANTES de activar el dashboard real

Con M5 conectado y firmware cargado:

```bash
cd /opt/dashboard_osciloscopio/real/raspberry
python3 probar_spi_fisico.py --rate 1000 --window 512 --spi-hz 2000000
```

Debe responder `PING`, luego `ACK config` (incluye la tasa y ventana solicitadas) y diez ventanas de muestras con su conteo de bytes SPI. Si falla `READY`, revisar cable de GPIO24 BCM (pin 18), CS, MOSI/MISO y que el ESP32 realmente tenga firmware correcto. Si falla CRC, bajar reloj a 1 MHz, acortar cables y revisar pinout. El firmware está configurado con **SPI modo 0**.

**Advertencia:** si eliges `window=1024` la respuesta SPI tiene 4.116 bytes y puede superar el búfer de `spidev` por defecto (habitualmente 4.096). Se recomienda N=512 en la primera integración; para N=1024 aumentar `spidev.bufsiz` a 8192 mediante la línea de arranque del kernel y reiniciar, comprobando el valor real en `/sys/module/spidev/parameters/bufsiz`.

## 4. Activar adquisición y publicación real

```bash
sudo systemctl enable --now pulsescope-spi.service
sudo systemctl status pulsescope-spi.service
sudo journalctl -u pulsescope-spi -f
```

Después abrir `http://IP_REAL_RASPBERRY/` desde un computador o celular **de la misma red**. En el dashboard, cambiar 100, 1.000, 10.000 y (experimentalmente) 40.000 Sa/s. La secuencia debe ser: navegador `POST /api/config` → adaptador Raspberry `GET /api/config` → comando SPI → **ACK ESP32** → lectura SPI con CRC → adaptador `POST /api/ingest` → navegador `GET /api/muestras`.

El backend siempre devuelve la configuración *solicitada*. El estado `spi_connected` y `applied_rate_hz` de `GET /api/estado` solo se activan cuando el adaptador declara haber obtenido ACK y recibido ventanas. **Ese estado NO certifica la tasa real, que requiere medición externa**.

Por seguridad Nginx bloquea `/api/ingest` y `/api/hardware` desde navegadores remotos. Los dos POST deben dirigirse por `127.0.0.1:8000`, **desde el SBC**, no mediante la IP pública de la Pi. Mantener red local confiable; no exponer HTTP a Internet sin autenticación y seguridad adicionales.

## 5. Pruebas previas SIN ningún equipo

En Windows, exactamente como antes:

```powershell
python demo_integracion.py
# http://127.0.0.1:8000
python -m unittest discover -s tests -v
python -m unittest discover -s real/tests -v
```

También está `PRUEBA_SIN_RASPBERRY.bat`: se conservó, igual que el generador artificial. Con el preset de 40.000 Sa/s el emulador solo configura el metadato de tiempo; **no está reproduciendo un ADC a 40 kHz**.

## 6. Escenarios que falta validar en laboratorio

- Compilación y ejecución en la **M5Stack exacta**, con periféricos de la placa sin conflicto.
- Fs 100, 1000, 10000 y 40000 **por canal**; estabilidad, muestras perdidas, jitter y corrección de escala de voltajes.
- SPI con CS, READY, longitud de ventana, CRC y tasa máxima experimental a varios clocks.
- Calibración del ADC y acondicionamiento de señales; amplitud/frecuencia reales con generador y osciloscopio.
- Latencia y actualización visual dentro de 1-4 s incluso con cambios de preset y reinicios.
- Nginx accesible por red, servicios tras reboot, permisos GPIO/SPI, escritura de logs y seguridad.

**Si la M5 no expone dos entradas ADC1 o los GPIO SPI previstos, hay que adaptar el hardware. Ningún ZIP puede garantizar el funcionamiento eléctrico antes de identificar la placa.**
