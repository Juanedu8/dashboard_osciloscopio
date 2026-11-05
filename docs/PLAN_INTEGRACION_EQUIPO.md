# Integración de los seis integrantes — v0.2

## Objetivo y límites

El dashboard se prueba sin Raspberry Pi con **un proveedor artificial externo**. El proveedor `emulador_sbc.py` hace exactamente dos acciones que hará el programa de la Raspberry: consulta la configuración solicitada y entrega las dos ventanas de muestras a la API. Esto verifica la unión de módulos **HTTP / JSON / interfaz**, no la adquisición ADC, las tasas físicas ni SPI.

## Flujo probado

```text
             EN DESARROLLO (SIN HARDWARE)
 Dashboard web -- POST /api/config --> Backend HTTP local
       ^                               |            ^
       |                        GET /api/config     | POST /api/ingest
  GET /api/muestras                     v            |
       +--------------------------- Emulador SBC ----+

              CON RASPBERRY Y M5STACK
 Dashboard web <-- API backend en SBC <-- adaptador de muestras
                                          ^
                                          | SPI real
                                          v
                                  Firmware M5Stack (ADC)
```

En ambos casos el dashboard solicita **GET `/api/muestras`**: el frontend no necesita cambiar. Solo se sustituye el proveedor `emulador_sbc.py` por el adaptador SPI que use `/api/config` y `/api/ingest`.

## Responsabilidades y archivos

| Rol | Archivo / interfaz | Entrega esperada |
| --- | --- | --- |
| 1. Firmware ADC | En M5Stack; fuera de este repo | 2 canales + temporizacion por preset + N muestras por canal |
| 2. Firmware/protocolo SPI | Trama SPI acordada con rol 3 | Comandos FS/N, ACK y envio de ventanas + integridad |
| 3. Software SBC | `adaptador_spi_plantilla.py` | Reemplazar lectura artificial por SPI real; publicar JSON en `/api/ingest` |
| 4. Dashboard | `web/index.html`, `web/styles.css`, `web/app.js` | Graficas, 3 presets y actualizacion de 1, 2 o 4 s |
| 5. Servidor/Red | `server.py`, `deploy/nginx.conf.example` | Configurar Nginx, backend local, acceso por red al dashboard |
| 6. Pruebas/documentacion | `tests/`, `docs/`, `resultado_pruebas.txt` | Matriz, evidencias con mediciones reales e integracion de modulo |

**Acordar antes del desarrollo SPI:** modelo exacto M5Stack, modelo Raspberry Pi, conectores y pines, maestro y esclavo, modo CPOL/CPHA, bits/palabra, clock maximo, limites de ADC, estructura binaria y checksum, comandos y ACK, asociacion temporal de ambos canales, gestion de desbordamientos. No estan determinados aun por esta demo.

## Prueba reproducible en 5 minutos

1. Ejecutar `python demo_integracion.py` (o `PRUEBA_SIN_RASPBERRY.bat`).
2. Abrir `http://127.0.0.1:8000`. Observar la fuente **EXTERNO**.
3. Modificar las frecuencias 100, 1000 y 10000 Sa/s. En consola se debe ver el nuevo preset (configuracion *simulada*); en la API cambia `dt_s`.
4. Seleccionar ventana 64 y despues 256. Comprobar en `/api/muestras` dos listas de esa longitud.
5. Elegir refresco 1, 2 y 4 s. Observar la cadencia de actualizacion de graficas.
6. Para comprobar interrupcion: `python demo_integracion.py --count 10`; tras enviar diez ventanas el emulador se detendra pero el servidor seguira ejecutandose. Pasados unos segundos el navegador debera indicar que faltan muestras recientes.
7. Ejecutar `python -m unittest discover -s tests -v` y guardar el resultado.

## Datos que la persona encargada de SPI entrega al dashboard

```json
{
  "sequence": 57,
  "sample_rate_hz": 1000,
  "samples_per_channel": 64,
  "unit": "V",
  "channel_1": [1.65, 1.70, 1.75],
  "channel_2": [0.98, 1.02, 1.05]
}
```

Los arreglos del ejemplo abreviado **no se aceptan como trama real**: deben tener los 64 o más valores completos acordes a `/api/config` (64, 256, 512 o 1024). Los datos deben ser números finitos entre 0 y 3,3 V, ambos arreglos de igual longitud; `sequence` debe crecer. La API añade `dt_s`, `mode`, `channel_count` y fecha si falta.

El adaptador convierte la representación física del ADC (códigos) a voltios **después de calibrar**. No enviar códigos ADC como si fueran voltios. Para tensión fuera de 0–3,3 V o una resolución/unidad distinta, deben acordarse y actualizarse el contrato y la escala del frontend.

## Aseguramiento y alcance

- `GET /api/muestras` devuelve **503** hasta tener datos recientes del proveedor. Esto permite detectar que el emulador o proceso de adquisición dejó de enviar ventanas.
- `POST /api/ingest` rechaza datos incoherentes con **400** (longitud, secuencia, rango, etc.) y no queda abierto en el proxy Nginx público.
- El modo demo **no** valida osciloscopio real, temporización, carga del ESP32, ancho de banda SPI, jitter, calibración, ni la bonificación de 40 000 Sa/s.
- El backend provisional escucha solo en `127.0.0.1` por defecto; no usar este servidor de desarrollo como servicio público. Nginx debe entregar estáticos y enlazar únicamente los endpoints API necesarios.
