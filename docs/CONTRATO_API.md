# Contrato JSON/HTTP — PulseScope v0.2

**Backend de desarrollo:** `http://127.0.0.1:8000` por defecto. El dashboard usa rutas relativas `/api/...`; no se requiere CORS ni librerías externas.

## 1. GET /api/config

```json
{
  "sample_rate_hz": 1000,
  "window_size": 512,
  "refresh_interval_s": 1,
  "mode": "external"
}
```

`mode` vale `simulation` (backend genera muestras) o `external` (alguien hace POST de ventanas, emulador o SPI real). `sample_rate_hz` es **muestras/s por canal**. El preset de backend es una **solicitud**, no un acuse físico del microcontrolador.

## 2. POST /api/config

`Content-Type: application/json`. Ejemplo: `{"sample_rate_hz":10000,"window_size":64,"refresh_interval_s":2}`. Se permite enviar solo uno de estos campos:

| Campo | Valores permitidos |
| --- | --- |
| `sample_rate_hz` | 100, 1000, 10000, 40000 (experimental) |
| `window_size` | 64, 256, 512, 1024 |
| `refresh_interval_s` | 1, 2, 4 segundos |

Respuesta HTTP 200 = configuración aceptada **por el backend**. HTTP 400 = invalidación. El software real SBC debe transferir el preset por SPI y esperar confirmación del uC antes de publicar datos con dicho preset.

## 3. POST /api/ingest — **Interfaz principal con el equipo SBC**

Solo habilitada con `python server.py --source external` o `python demo_integracion.py`.

Ejemplo **abreviado, no válido para enviar hasta completar los 64 valores de cada canal**:

```json
{
  "sequence": 12,
  "sample_rate_hz": 1000,
  "samples_per_channel": 64,
  "unit": "V",
  "generated_at_utc": "2026-10-30T18:00:00.000+00:00",
  "channel_1": [1.20, 1.23, 1.25],
  "channel_2": [0.45, 0.47, 0.50]
}
```

**Campos requeridos:** `sequence` entero positivo estrictamente creciente, `sample_rate_hz` entero, `channel_1` y `channel_2` arreglos completos. Campos opcionales: `samples_per_channel`, `unit` (solo `V`) y `generated_at_utc` (ISO 8601 con zona horaria, preferiblemente UTC). Si se omite la fecha el backend pone su reloj UTC de recepción (no es un timestamp del ADC).

**Validaciones:** longitudes iguales y compatibles con `/api/config`, mínimo 64, máximo 1024, voltajes numéricos finitos de 0 a 3,3 V, `sample_rate_hz` igual a `/api/config`, secuencia mayor a la anterior. Error de validación => HTTP 400 y `{"error":"..."}`; envío correcto => HTTP 200 `{"accepted":true,"sequence":12,"frames_received":12}`. Se aceptan hasta 128 KiB por solicitud.

**Contrato a actualizar con hardware:** voltaje ADC válido (calibración, ADC externo), bits de conversión, timestamps desde firmware, checksum y cantidad de muestras si se cambia el diseño. **No confundir valores ADC brutos con voltios**.

## 4. GET /api/muestras — **Interfaz del dashboard**

```json
{
  "mode": "external",
  "sequence": 12,
  "generated_at_utc": "2026-10-30T18:00:00.000+00:00",
  "sample_rate_hz": 1000,
  "dt_s": 0.001,
  "samples_per_channel": 64,
  "channel_count": 2,
  "unit": "V",
  "channel_1": [/* array de 64 números */],
  "channel_2": [/* array de 64 números */]
}
```

Los comentarios dentro del JSON mostrado arriba son ilustrativos; para parsear JSON real hay que sustituirlos por números. En la API, `channel_1` y `channel_2` contienen 64 o más elementos completos. `dt_s = 1/sample_rate_hz` y el frontend dibuja el eje X en milisegundos. **No se afirma que en la simulación se tome una muestra física cada `dt_s`**.

Si no existe una ventana reciente y coherente con la configuración, devuelve **HTTP 503** con JSON de error. Una ventana se considera obsoleta después de `max(2 s, 2 × refresh_interval_s)` segundos sin nuevos POST. El navegador enseña un mensaje en vez de fingir adquisición en vivo.

## 5. GET /api/estado

En modo externo incluye `ok`, `mode`, `source`, `channels`, `ingest_connected`, `frames_received`, `last_frame_age_s`, `spi_connected`, `sbc_connected`. En esta demo `spi_connected` y `sbc_connected` permanecen **false**: no se trata de telemetría de hardware real. La implementación en SBC tendrá que verificar y comunicar la conexión física si se requiere.

## Guía de conexión en Raspberry

1. Servir **web/** con Nginx o Apache; proxy HTTP `/api/config`, `/api/muestras`, `/api/estado` al backend.
2. Backend local: `python server.py --source external --host 127.0.0.1`.
3. Adaptador SPI en el mismo SBC: consultar GET `/api/config`, configurar ESP32 por SPI, recibir 2 canales, convertir a V, y POST `http://127.0.0.1:8000/api/ingest`.
4. No dar acceso público al endpoint de escritura `/api/ingest`, ni exponer `http.server` a internet.
5. Para completar cumplimiento: verificar Nginx, que el preset llegue al uC por SPI, clocks estables y transferencia binaria. **El emulador no verifica estas obligaciones**.


## Extensión opcional para sistema REAL (sin romper v0.2)

`POST /api/hardware` se recibe **solo desde 127.0.0.1:8000**, publicado por el adaptador `real/raspberry/ejecutar_spi_real.py` (Nginx **bloquea** el acceso remoto). Ejemplo:

```json
{"spi_connected":true,"applied_rate_hz":40000,"applied_window_size":512,"detail":"ACK ESP32 y datos SPI"}
```

Si no hay conexión, enviar `{ "spi_connected": false, "applied_rate_hz": null, "applied_window_size": null, "detail": "Desconectado" }`.

`GET /api/estado` incluye información reportada por el adaptador: `spi_connected`, `sbc_connected`, `applied_rate_hz`, `applied_window_size`, `hardware_detail`. El backend **no infiere ni certifica Fs física solo desde el ACK**. Al cambiar preset, se invalida la confirmación hasta recibir otra.

La lista de presets de la versión extendida es **100, 1.000, 10.000, 40.000 Sa/s**, siendo 40.000 exclusivamente un bono experimental. El formato de `POST /api/ingest` y de `GET /api/muestras` permanece igual que en v0.2.
