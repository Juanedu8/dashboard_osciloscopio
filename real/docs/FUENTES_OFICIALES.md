# Referencias para contrastar con la hoja de datos del equipo

- ESP-IDF 5.5, modo continuo ADC ESP32: https://docs.espressif.com/projects/esp-idf/en/release-v5.5/esp32/api-reference/peripherals/adc_continuous.html
- Ejemplo oficial ADC continuo y patrones de ADC1: https://github.com/espressif/esp-idf/tree/release/v5.5/examples/peripherals/adc/continuous_read
- Driver SPI esclavo ESP32: https://docs.espressif.com/projects/esp-idf/en/release-v5.5/esp32/api-reference/peripherals/spi_slave.html
- SPI en Raspberry Pi: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html

**Es obligatorio contrastar** con la hoja de datos de ESP32-D0WDQ6 y el esquemático de la M5Stack concreta: pines ADC/SPI, tensiones, restricciones de periféricos y strap/arranque. Los límites SPI teóricos de referencia no sustituyen mediciones de cada montaje.
