# Bonificación experimental: 40.000 Sa/s por canal

Se añadió a la **interfaz web**, al **validador API**, al **protocolo SPI** y al firmware ESP-IDF un preset de **40.000 Sa/s por canal**. Eso es una **capacidad implementada en código**, no un resultado físico probado.

## Fundamento

El ESP32-D0WDQ6 tiene ADC1 con posibilidad de muestreo continuo mediante DMA. Se programa `sample_freq_hz=80000` (total sobre dos canales alternados) para aspirar a `Fs1≈40.000`, `Fs2≈40.000` Sa/s. Los tres presets obligatorios se generan desde 20.000 conversiones/s agregadas (`10.000/canal`) con submuestreo entero `100:1`, `10:1`, `1:1`. N=64, 256, 512, 1024 se representa con los mismos campos del dashboard.

## Plan experimental concreto

1. **Calibrar señal:** generador con señal periódica conocida y amplitud válida para el ADC (p. ej., senoidal de 2 kHz sobre un offset que evite voltajes negativos). Medir amplitud/frecuencia en un osciloscopio de referencia.
2. **Medir el ESP32:** solicitar 40.000 Sa/s en el dashboard; comprobar en ESP32 `METRIC target=40000; counted CH1=..., CH2=... Sa/s` durante >10 s. Guardar el registro. El conteo por software confirma **volumen promedio**, no por sí solo intervalo constante.
3. **Verificar tiempo entre muestras:** adquirir ventanas de señal periódica y ajustar su periodo en muestras; por ejemplo, a Fs=40.000 Sa/s una señal de 2.000 Hz debe mostrar ≈20 muestras por periodo. Repetir con distintas frecuencias y canales. Comparar contra generador/osciloscopio; estimar error porcentual. Para estimar jitter/muestreo estrictamente uniforme, usar instrumentación de referencia o timestamps/medición independiente del ADC. **No usar el `dt_s` del JSON como prueba**, es un valor calculado.
4. **Medir rendimiento SPI:** correr `python3 probar_spi_fisico.py --rate 40000 --window 512 --spi-hz 2000000 --count 100`; registrar bytes transferidos/segundo, errores CRC y ventanas nuevas. Barrer 1, 2, 4 MHz; detenerse si aparecen errores.
5. **UI real:** cada control debe enviar el nuevo preset al ESP32 y obtener ACK; esperar N muestras reales, comprobar que el modo indica `SPI REAL`, que la gráfica refresque dentro de 1–4 s y que el estado no quede marcado como verificado al desconectar el cable.
6. **Matriz:** anotar frecuencia nominal, frecuencia calculada con medida independiente, canal, voltajes, N, tiempo total, SPI Hz, tasa SPI medida, CRC incorrectos, ventanas perdidas y evidencia (captura + CSV + video). Repetir ≥3 corridas y reportar incertidumbre.

## Precauciones

- 40.000 Sa/s **por canal** equivale a 80.000 conversiones ADC/s sumadas; no confundir frecuencia agregada con frecuencia por canal.
- Nyquist teórico por canal 20 kHz, pero el ADC analógico, ruido y filtro anti-aliasing limitan la calidad. Usar señales de prueba bien por debajo de Nyquist.
- ESP32 ADC clásico no es metrología de precisión sin calibración; la transformación por defecto `raw * 3.3/4095` es aproximada.
- El emulador puede mostrar el preset 40.000 y pasar pruebas, pero **no demuestra capturas físicas a 40.000**.
- La M5 concreta podría reservar GPIO y los dos canales ADC elegidos podrían ser inaccesibles; adaptar hardware antes de las pruebas.
