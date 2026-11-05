# Contrato físico SPI PSC1, versión 1

**SPI master:** Raspberry Pi Zero 2 W, SPI0/CE0; **slave:** ESP32 original. Mode=0, 8 bits, byte order little endian. READY (GPIO extra): ESP32 pone READY=1 cuando el periférico esclavo está preparado para una transferencia; vuelve a 0 al terminar. Master espera transición 0→1 entre comando y respuesta.

## Intercambio de dos etapas

1. Raspberry espera READY=1, envía comando de **16 bytes** (CS deassert al terminar).
2. ESP32 recibe, interpreta, prepara respuesta y pone READY=1; master realiza **segunda** transacción, lectura de 20 o `20+4*N` bytes.
3. ESP32 vuelve READY=0 tras la segunda transferencia; la Raspberry espera la próxima preparación antes de enviar otro comando.

### Comando, 16 bytes

`<4sBBHII`, little endian: `magic='PSC0' (4); version=1 (u8); cmd (u8); N (u16); Fs (u32); reserved=0 (u32)`.

- `cmd=1` CONFIG: N en 64/256/512/1024 y Fs en 100/1000/10000/40000 por canal. **Esperar confirmación** antes de publicar ventanas de la frecuencia nueva.
- `cmd=2` GET_WINDOW: N y Fs se ignoran; respuesta contiene la última ventana capturada (no necesariamente todas las ventanas ADC producidas).
- `cmd=3` PING: respuesta de estado.

### Respuesta, cabecera de 20 bytes

`<4sBBHIIHH`: `magic='PSC1' (4); version=1 (u8); status (u8); N (u16); Fs (u32); sequence (u32); crc16 (u16); reserved=0 (u16)`.

- Status: 0=OK, 1=no hay nueva ventana todavía, 2=petición inválida, 3=falló ADC.
- Respuestas CONFIG/PING: 20 bytes en total.
- Respuesta GET_WINDOW: 20 + 4*N bytes. Incluso si `status=1`, la longitud de transferencia es la de la ventana y el payload es cero.
- Payload: `N` pares alternados `ch1_raw(u16), ch2_raw(u16)`, cada ADC en 12 bits 0..4095.
- CRC16-CCITT, polinomio 0x1021, init 0xFFFF: CRC sobre `header[0:16] + payload` (excluye bytes 16..19 de cabecera), usando `binascii.crc_hqx(..., 0xFFFF)` en Python.
- `sequence` se incrementa al cerrar/publicar una nueva ventana en el firmware. La Raspberry evita reutilizar una ventana con número igual o inferior.

### Requisitos eléctricos y temporales

La tasa máxima **teórica** del esclavo ESP32 según documentación Espressif es ~10 MHz en condiciones ideales, y el uso de GPIO-matrix reduce el margen de MISO. Configuración conservadora inicial de este proyecto: **SPI 2 MHz**. Verificar por barrido (1, 2, 4 MHz) y CRC en pruebas reales; no se ha certificado ninguno de esos valores. La Pi puede soportar relojes más altos, pero manda el límite del conjunto chip+pinout+cables+firmware.

Para 40 kSa/s por canal, dos canales de 12 bits enviados en contenedores de 16 bits requieren, en datos puros:

`2 canales * 40.000 muestras/s/canal * 2 bytes/muestra = 160.000 bytes/s = 1,28 Mbit/s`.

Ese valor **ignora** las cabeceras, la transacción de comando, READY, latencias de Python/Linux y las ventanas que se descarten al usar un búfer de captura más reciente. El proyecto transmite *ventanas*, no garantiza el streaming de absolutamente todas las muestras si el lector es más lento que el firmware. El requisito principal habla de captura por ventanas y frecuencia de muestreo, no de streaming sin pérdida; no atribuirle una prueba de throughput continuo a esta implementación.

Para N=512, respuesta ocupa `20 + 4*512 = 2068 bytes`; a 2 MHz, tiempo de bits ideal ≈ 8,27 ms (sin overhead). A 40 kSa/s por canal, una ventana de 512 muestras cubre 12,8 ms de señal. Debe medirse experimentalmente si el transporte y el planificador mantienen la tasa de publicación necesaria.
