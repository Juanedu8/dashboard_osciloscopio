# Qué cambió respecto al ZIP v0.2 que ya funcionaba

**La prueba sin Raspberry se conserva.** Los siguientes archivos fueron copiados de la versión previa sin modificar: `PRUEBA_SIN_RASPBERRY.bat`, `demo_integracion.py`, `emulador_sbc.py`, `web/styles.css`, `start_windows.bat` y `start_linux.sh`.

**Cambios aditivos mínimos:**

- `web/index.html`: botón nuevo `40.000 ★` junto a los tres existentes, sin rediseñar layout.
- `web/app.js`: informa `SPI REAL` solamente cuando el adaptador del SBC comunica un ACK + ventanas actuales; conserva gráficos, colores y refresco originales.
- `server.py`: acepta `sample_rate_hz=40000` como preset experimental y añade `POST /api/hardware` para telemetría **local**. Los endpoints anteriores conservan sus estructuras.
- `deploy/nginx.conf.example`: bloquea además `/api/hardware` para que únicamente el servicio local informe estado físico.
- `tests/test_api.py`: cambia un caso de frecuencia ilegal `40000` a `42000`, dado que 40000 pasó a ser permitido.
- `real/`: directorio **nuevo** con firmware ESP-IDF, integración Python SPI, configuración Raspberry/Nginx, contrato binario, verificaciones y documentación.

**Resultados automáticos de esta versión:** 15 pruebas web/API + 5 pruebas de protocolo SPI = **20 aprobadas** en el entorno de desarrollo. Incluye una prueba HTTP adicional con servidor/emulador a 40.000 Sa/s **simulados**. No se han ejecutado pruebas en M5Stack ni en Raspberry Pi reales. **No se ha compilado** el firmware en ESP-IDF dentro de este entorno, que no tiene la cadena de herramientas instalada.
