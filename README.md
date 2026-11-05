# PulseScope — versión de prueba conservada + extensión REAL + bono 40.000 Sa/s

**Inicia aquí:** `real/docs/GUIA_IMPLEMENTACION_REAL.md` para integrar Raspberry Pi y ESP32;
`real/docs/BONIFICACION_40000.md` para el bono;
`real/docs/PROTOCOLO_SPI_PSC1.md` para el contrato del equipo.

**Sin Raspberry (exactamente como antes):** doble clic en `PRUEBA_SIN_RASPBERRY.bat`
o `python demo_integracion.py`; abrir http://127.0.0.1:8000.

**Pruebas:** `python -m unittest discover -s tests -v` y
`python -m unittest discover -s real/tests -v`.

**Cambios mínimos a la base:** conserva las gráficas y diseño visual. Se añadió
el botón experimental 40.000 Sa/s, su validación HTTP y el indicador de SPI
cuando el adaptador real reporte ACK+ventanas. No se alteró la ruta de
integración artificial. Los archivos de Raspberry + firmware están en `real/`.

**Precaución:** el firmware es un proyecto de referencia para ESP32 original,
no ha sido compilado en la M5Stack específica ni probado con hardware de este
usuario. Para lograr y demostrar 40.000 Sa/s por canal deben verificar ADC,
SPI y temporización físicamente; la simulación no los valida.

---

# PulseScope — Dashboard de 2 canales (Proyecto 2)

**Versión 0.2: simulación e integración artificial sin Raspberry Pi**. Diseñado para conectar después un M5Stack con ESP32-D0WDQ6 y una Raspberry Pi vía SPI, con un dashboard accesible por HTTP.

> **Importante:** ahora se usan solo datos ficticios. Las frecuencias de 100, 1.000 y 10.000 Sa/s son parámetros representados y transmitidos por JSON, **no mediciones ni pruebas de frecuencia física**. Tampoco hay enlace SPI real.

## Cómo probarlo YA en Windows (sin Raspberry)

1. Descomprimir el ZIP. Tener **Python 3.9 o superior** instalado (no se requieren paquetes externos, ni npm, ni internet).
2. Abrir la carpeta `dashboard_osciloscopio`.
3. Ejecutar **`PRUEBA_SIN_RASPBERRY.bat`** (doble clic). Alternativamente abrir la terminal y ejecutar:

   ```powershell
   python demo_integracion.py
   ```

   Si Windows tiene el lanzador `py` en lugar de `python`, usar `py demo_integracion.py`.
4. Abrir **http://127.0.0.1:8000** en el navegador, no el archivo `web/index.html` por separado.
5. Ver dos gráficas con señales *artificiales distintas* (senoidal y triangular). Modificar los tres presets, ventanas de 64 a 1024 muestras y refresco de 1, 2 o 4 segundos. El emulador imprimirá cada ventana transmitida en la terminal.
6. Detener con **Ctrl+C**. Si el puerto 8000 ya está ocupado, cerrar el proceso anterior o ejecutar `python demo_integracion.py --port 8001` y abrir `http://127.0.0.1:8001`.

**El montaje de prueba ya verifica el camino externo:**

```text
Emulador SBC (Windows) --> HTTP POST /api/ingest --> Backend local
                                                       |
Navegador <-- HTTP GET /api/muestras ------------------+
            --> HTTP POST /api/config
Emulador   <-- HTTP GET /api/config (nuevo preset)
```

La transmisión de una ventana por `/api/ingest` utiliza el mismo contrato que implementará el adaptador del SBC. La gráfica no sabe si recibe muestras artificiales o de hardware.

## Segunda prueba: detectar que el proveedor dejó de transmitir

```powershell
python demo_integracion.py --count 10
```

La terminal enviará 10 ventanas y se detendrá la simulación externa, **pero el servidor queda activo**. El dashboard debe advertir que no llegan datos recientes, sin fingir una captura nueva. Salir con Ctrl+C.

## Otra opción: prueba rápida sin emulador externo

`start_windows.bat` o `python server.py` activa el simulador **interno** del servidor, la versión más sencilla. Para la prueba de integración modular use `demo_integracion.py`, pues esa sí comprueba `/api/ingest` desde un módulo separado.

También se pueden iniciar los dos módulos en **terminales separadas**:

```powershell
# Terminal A: backend sin generación de señales
python server.py --source external
# Terminal B: proveedor de ventanas artificiales
python emulador_sbc.py
```

## Configuración y contrato para otros integrantes

| Método | Ruta | Responsable / función |
| --- | --- | --- |
| GET | `/api/config` | El adaptador del SBC consulta el preset solicitado |
| POST | `/api/config` | El navegador solicita Fs, N y refresco |
| POST | `/api/ingest` | El emulador o el adaptador SPI entrega dos canales completos |
| GET | `/api/muestras` | El navegador obtiene la ventana reciente |
| GET | `/api/estado` | Estado de proveedor, contador de ventanas, antigüedad de datos |

- **Frecuencia:** 100, 1000, 10000 Sa/s por canal.
- **Ventana:** 64, 256, 512, 1024 muestras por canal (el requisito es al menos 64).
- **Refresco web:** 1, 2 o 4 s (equivalente a 1, 0,5 o 0,25 Hz).
- **Muestras:** listas de igual longitud, voltios entre 0 y 3,3 V. Se rechazan datos inconsistentes (HTTP 400).
- **Desconexión:** si no llega una ventana nueva durante `max(2, 2 × refresco)` segundos, `/api/muestras` responde 503 y la web muestra error. No implica conexión física SPI.

Ver especificación completa en **`docs/CONTRATO_API.md`**, ejemplo JSON válido en `ejemplos/ventana_64_valida.json` y asignación de responsabilidades en **`docs/PLAN_INTEGRACION_EQUIPO.md`**.

## Pruebas automáticas

Desde la carpeta del proyecto:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas verifican HTTP, presets, validación de ventanas, paso de dos canales del emulador a la API, secuencias duplicadas, cambios de configuración y detección de datos viejos. **No** verifican ADC, reloj de muestreo real, SPI, hardware o despliegue de la Raspberry Pi.

## Qué cambia cuando llegue la Raspberry Pi

1. Rol del ESP32: firmware que adquiere dos señales y administra ventanas con muestreo de reloj **real**.
2. Rol de SPI: acordar trama binaria, modo SPI, clock, acuse de cambios de preset, tamaño, sincronía e integridad.
3. Rol SBC: implementar `SPIHardware.apply_config()` y `SPIHardware.read_window()` en **`adaptador_spi_plantilla.py`**, siguiendo el contrato acordado con los encargados del firmware.
4. El adaptador del SBC envía los valores convertidos a voltios a `/api/ingest`; la UI web **no cambia**.
5. Rol despliegue: usar **Nginx o Apache** en el SBC para servir la página y exponer los endpoints de lectura/control; un ejemplo está en `deploy/nginx.conf.example` (bloquea `/api/ingest` desde la red). Ejecutar el backend ligado a `127.0.0.1` en el SBC.
6. Rol pruebas: medir realmente 100/1000/10000 Sa/s, tiempos por canal, máxima velocidad SPI experimental, integridad de datos y cadencia web.

`adaptador_spi_plantilla.py` **es una plantilla explícita**; aún no implementa SPI ni ACK porque depende de la placa concreta y del protocolo acordado. El servidor de desarrollo basado en `http.server` no sustituye Nginx/Apache ni es apropiado para exponerse a internet.

## Estructura

```text
dashboard_osciloscopio/
├── PRUEBA_SIN_RASPBERRY.bat    <- Emulador y servidor en una terminal
├── demo_integracion.py         <- Lanza prueba HTTP externa
├── emulador_sbc.py             <- Imita al modulo SPI de la Raspberry
├── adaptador_spi_plantilla.py  <- Punto exacto para integrar hardware real
├── server.py                   <- API HTTP y modos simulation/external
├── start_windows.bat           <- Simulacion interna simple
├── start_linux.sh
├── web/                        <- HTML/CSS/JavaScript del dashboard
├── docs/CONTRATO_API.md
├── docs/PLAN_INTEGRACION_EQUIPO.md
├── deploy/nginx.conf.example
├── tests/test_api.py
├── tests/test_external.py
├── ejemplos/ventana_64_valida.json
├── vista_integracion_externa.png
└── resultado_pruebas.txt       <- Salida de pruebas ejecutadas
```

Como evidencia para el informe, registrar capturas de la interfaz, respuestas JSON, salida de pruebas y errores detectados. Separar explícitamente los resultados *simulados* de las futuras mediciones físicas.
