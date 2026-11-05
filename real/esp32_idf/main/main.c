/*
 * PulseScope ESP32 (chip ESP32 original) - ESP-IDF 5.5 reference integration.
 * ADC1 two-channel continuous DMA + decimation for Fs/channel 100/1k/10k/40k.
 * SPI2 slave mode 0, CRC16-CCITT, GPIO READY. Tested at software/protocol level
 * only; ALWAYS confirm pins exposed on the exact M5Stack and measure sample clock.
 *
 * IMPORTANT: The chosen default pins are EXAMPLES, NOT certified safe for an M5.
 * Screen, flash, buttons, power-monitor and strapping pins differ by model.
 * SPI GPIOs must be changed before connecting if used by onboard peripherals.
 * ADC1 channels 6/7 map to GPIO34/GPIO35 on original ESP32; verify exposure.
 */
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "esp_log.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "esp_attr.h"
#include "driver/gpio.h"
#include "driver/spi_slave.h"
#include "esp_adc/adc_continuous.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "soc/soc_caps.h"

#define PS_SPI_MOSI_GPIO 23
#define PS_SPI_MISO_GPIO 19
#define PS_SPI_SCLK_GPIO 18
#define PS_SPI_CS_GPIO    5
#define PS_READY_GPIO    27
#define PS_ADC_CH1       ADC_CHANNEL_6   /* ESP32 GPIO34; ADC1 only */
#define PS_ADC_CH2       ADC_CHANNEL_7   /* ESP32 GPIO35; ADC1 only */
#define PS_MAX_SAMPLES   1024
#define PS_HEADER_BYTES  20
#define PS_MAX_REPLY     (PS_HEADER_BYTES + 4 * PS_MAX_SAMPLES)
#define PS_ADC_READ_LEN  512
#define PS_CMD_CONFIG    1
#define PS_CMD_FRAME     2
#define PS_CMD_PING      3
#define PS_OK            0
#define PS_NO_DATA       1
#define PS_BAD_REQUEST   2
#define PS_ADC_ERROR     3

static const char *TAG = "PULSESCOPE";
static adc_continuous_handle_t adc_handle;
static bool adc_running = false;
static QueueHandle_t config_req, config_reply;
static SemaphoreHandle_t capture_lock;
static uint32_t current_rate = 1000;
static uint16_t current_n = 512;
static uint32_t latest_seq = 0;
static bool latest_valid = false;
static uint16_t latest[2][PS_MAX_SAMPLES];
static uint16_t building[2][PS_MAX_SAMPLES];
static size_t ring_position[2] = {0, 0};
static size_t ring_filled[2] = {0, 0};
static uint32_t new_since_publish[2] = {0, 0};
static uint32_t per_ch_conversion_count[2] = {0, 0};
static uint64_t stats_kept[2] = {0, 0};
static int64_t stats_start_us = 0;
static DMA_ATTR uint8_t spi_reply[PS_MAX_REPLY];
static DMA_ATTR uint8_t spi_cmd_rx[16];
static DMA_ATTR uint8_t spi_cmd_dummy[16];
static DMA_ATTR uint8_t spi_reply_rx[PS_MAX_REPLY];

typedef struct { uint32_t rate; uint16_t n; } acquire_config_t;
typedef struct { esp_err_t result; uint32_t rate; uint16_t n; } acquire_result_t;

static void write_u16(uint8_t *dst, uint16_t value) {
    dst[0] = value & 0xff; dst[1] = (value >> 8) & 0xff;
}
static void write_u32(uint8_t *dst, uint32_t value) {
    for (int i = 0; i < 4; ++i) dst[i] = (value >> (8 * i)) & 0xff;
}
static uint16_t read_u16(const uint8_t *src) {
    return (uint16_t)(src[0] | (src[1] << 8));
}
static uint32_t read_u32(const uint8_t *src) {
    return ((uint32_t)src[0]) | ((uint32_t)src[1] << 8)
           | ((uint32_t)src[2] << 16) | ((uint32_t)src[3] << 24);
}
static uint16_t crc_advance(uint16_t crc, uint8_t b) {
    crc ^= (uint16_t)b << 8;
    for (int i = 0; i < 8; i++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
    return crc;
}
static uint16_t reply_crc(const uint8_t *p, size_t payload_bytes) {
    uint16_t crc = 0xffff;
    for (int i = 0; i < 16; i++) crc = crc_advance(crc, p[i]);
    for (size_t i = 0; i < payload_bytes; i++) crc = crc_advance(crc, p[20 + i]);
    return crc;
}
static bool valid_config(uint32_t rate, uint16_t n) {
    bool good_rate = rate == 100 || rate == 1000 || rate == 10000 || rate == 40000;
    bool good_n = n == 64 || n == 256 || n == 512 || n == 1024;
    return good_rate && good_n;
}
static void IRAM_ATTR spi_ready_cb(spi_slave_transaction_t *t) { gpio_set_level(PS_READY_GPIO, 1); }
static void IRAM_ATTR spi_done_cb(spi_slave_transaction_t *t) { gpio_set_level(PS_READY_GPIO, 0); }

/* The ESP32 ADC_DIGI clock sets AGGREGATE conversion rate across 2 channels.
 * For <= 10k Sa/s/ch run 20k conv/s => 10k/ch and integer decimation.
 * For 40k Sa/s/ch run 80k conv/s => 40k/ch with no decimation.
 */
static esp_err_t configure_adc(uint32_t fs_per_channel) {
    if (adc_running) {
        esp_err_t stop = adc_continuous_stop(adc_handle);
        if (stop != ESP_OK) return stop;
        adc_running = false;
    }
    adc_digi_pattern_config_t pattern[2] = {0};
    pattern[0].atten = ADC_ATTEN_DB_12;
    pattern[0].channel = PS_ADC_CH1;
    pattern[0].unit = ADC_UNIT_1;
    pattern[0].bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
    pattern[1].atten = ADC_ATTEN_DB_12;
    pattern[1].channel = PS_ADC_CH2;
    pattern[1].unit = ADC_UNIT_1;
    pattern[1].bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
    adc_continuous_config_t cfg = {
        .pattern_num = 2,
        .adc_pattern = pattern,
        .sample_freq_hz = fs_per_channel == 40000 ? 80000 : 20000,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        .format = ADC_DIGI_OUTPUT_FORMAT_TYPE1,
    };
    esp_err_t err = adc_continuous_config(adc_handle, &cfg);
    if (err != ESP_OK) return err;
    err = adc_continuous_start(adc_handle);
    if (err == ESP_OK) adc_running = true;
    return err;
}

static void acquisition_task(void *arg) {
    uint8_t data[PS_ADC_READ_LEN];
    uint32_t out_bytes;
    ESP_ERROR_CHECK(configure_adc(current_rate));
    stats_start_us = esp_timer_get_time();
    while (1) {
        acquire_config_t wanted;
        if (xQueueReceive(config_req, &wanted, 0) == pdTRUE) {
            esp_err_t err = configure_adc(wanted.rate);
            if (err == ESP_OK) {
                xSemaphoreTake(capture_lock, portMAX_DELAY);
                current_rate = wanted.rate;
                current_n = wanted.n;
                latest_valid = false;
                ring_position[0] = ring_position[1] = 0;
                ring_filled[0] = ring_filled[1] = 0;
                new_since_publish[0] = new_since_publish[1] = 0;
                per_ch_conversion_count[0] = per_ch_conversion_count[1] = 0;
                stats_kept[0] = stats_kept[1] = 0;
                stats_start_us = esp_timer_get_time();
                xSemaphoreGive(capture_lock);
                ESP_LOGI(TAG, "ADC DMA configurado: %lu Sa/s/canal objetivo, N=%u",
                         (unsigned long)wanted.rate, wanted.n);
            } else {
                ESP_LOGE(TAG, "ADC config error: %s", esp_err_to_name(err));
            }
            acquire_result_t result = { err, current_rate, current_n };
            xQueueSend(config_reply, &result, portMAX_DELAY);
        }
        esp_err_t err = adc_continuous_read(adc_handle, data, sizeof(data), &out_bytes, 20);
        if (err == ESP_ERR_TIMEOUT) continue;
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "ADC lectura: %s; posible overflow DMA", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(1));
            continue;
        }
        uint32_t divider = (current_rate == 40000) ? 1 : 10000 / current_rate;
        for (uint32_t offset = 0; offset + SOC_ADC_DIGI_RESULT_BYTES <= out_bytes;
             offset += SOC_ADC_DIGI_RESULT_BYTES) {
            const adc_digi_output_data_t *sample = (const void *)(data + offset);
            int ch = sample->type1.channel == PS_ADC_CH1 ? 0 :
                     (sample->type1.channel == PS_ADC_CH2 ? 1 : -1);
            if (ch < 0) continue;
            uint32_t index = per_ch_conversion_count[ch]++;
            if ((index % divider) != 0) continue;
            stats_kept[ch]++;
            building[ch][ring_position[ch]] = sample->type1.data & 0x0fff;
            ring_position[ch] = (ring_position[ch] + 1) % current_n;
            if (ring_filled[ch] < current_n) ring_filled[ch]++;
            new_since_publish[ch]++;
            /* Sliding window: after initial fill, publish at least ~2/s even
             * when N=1024 and Fs=100 Sa/s (N/Fs is 10.24 s). */
            uint32_t stride = current_rate / 2;
            if (stride < 1) stride = 1;
            if (stride > current_n) stride = current_n;
            if (ring_filled[0] == current_n && ring_filled[1] == current_n &&
                new_since_publish[0] >= stride && new_since_publish[1] >= stride) {
                xSemaphoreTake(capture_lock, portMAX_DELAY);
                for (int c = 0; c < 2; c++) {
                    for (int k = 0; k < current_n; k++) {
                        latest[c][k] = building[c][(ring_position[c] + k) % current_n];
                    }
                }
                latest_seq++;
                latest_valid = true;
                xSemaphoreGive(capture_lock);
                new_since_publish[0] = new_since_publish[1] = 0;
            }
        }
        /* Diagnostic estimate from number of decimated conversions divided by
         * elapsed wall time. Corroborate with oscilloscope/generator; software
         * timing is NOT proof of equidistant ADC sample instants. */
        int64_t now_us = esp_timer_get_time();
        if (now_us - stats_start_us >= 5000000) {
            const double secs = (now_us - stats_start_us) / 1000000.0;
            ESP_LOGI(TAG, "METRIC target=%lu Sa/s/ch; counted CH1=%.1f CH2=%.1f Sa/s; windows seq=%lu",
                     (unsigned long)current_rate, stats_kept[0] / secs,
                     stats_kept[1] / secs, (unsigned long)latest_seq);
            stats_kept[0] = stats_kept[1] = 0;
            stats_start_us = now_us;
        }
    }
}

static void make_reply(uint8_t status, uint16_t n, uint32_t fs, uint32_t seq,
                       const uint16_t *ch0, const uint16_t *ch1, bool include_samples) {
    memset(spi_reply, 0, include_samples ? PS_HEADER_BYTES + 4 * n : PS_HEADER_BYTES);
    memcpy(spi_reply, "PSC1", 4);
    spi_reply[4] = 1; spi_reply[5] = status;
    write_u16(spi_reply + 6, n);
    write_u32(spi_reply + 8, fs);
    write_u32(spi_reply + 12, seq);
    if (include_samples && status == PS_OK) {
        for (int i = 0; i < n; ++i) {
            write_u16(spi_reply + 20 + i * 4, ch0[i]);
            write_u16(spi_reply + 22 + i * 4, ch1[i]);
        }
    }
    uint16_t crc = reply_crc(spi_reply, include_samples ? 4 * n : 0);
    write_u16(spi_reply + 16, crc);
}

static void spi_task(void *arg) {
    gpio_config_t ready_cfg = {
        .pin_bit_mask = (1ULL << PS_READY_GPIO), .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&ready_cfg));
    gpio_set_level(PS_READY_GPIO, 0);
    spi_bus_config_t bus = {
        .mosi_io_num = PS_SPI_MOSI_GPIO,
        .miso_io_num = PS_SPI_MISO_GPIO,
        .sclk_io_num = PS_SPI_SCLK_GPIO,
        .quadwp_io_num = -1, .quadhd_io_num = -1,
        .max_transfer_sz = PS_MAX_REPLY,
    };
    spi_slave_interface_config_t slave = {
        .spics_io_num = PS_SPI_CS_GPIO, .mode = 0,
        .queue_size = 2, .post_setup_cb = spi_ready_cb, .post_trans_cb = spi_done_cb,
    };
    ESP_ERROR_CHECK(spi_slave_initialize(SPI2_HOST, &bus, &slave, SPI_DMA_CH_AUTO));
    ESP_LOGI(TAG, "SPI slave listo: MOSI=%d MISO=%d SCLK=%d CS=%d READY=%d",
             PS_SPI_MOSI_GPIO, PS_SPI_MISO_GPIO, PS_SPI_SCLK_GPIO,
             PS_SPI_CS_GPIO, PS_READY_GPIO);
    while (1) {
        memset(spi_cmd_rx, 0, sizeof(spi_cmd_rx));
        spi_slave_transaction_t cmd = { .length = 16 * 8,
                                       .tx_buffer = spi_cmd_dummy, .rx_buffer = spi_cmd_rx };
        ESP_ERROR_CHECK(spi_slave_transmit(SPI2_HOST, &cmd, portMAX_DELAY));
        uint8_t action = spi_cmd_rx[5];
        bool valid = cmd.trans_len == 128 && !memcmp(spi_cmd_rx, "PSC0", 4)
                     && spi_cmd_rx[4] == 1 && read_u32(spi_cmd_rx + 12) == 0;
        uint16_t wanted_n = read_u16(spi_cmd_rx + 6);
        uint32_t wanted_rate = read_u32(spi_cmd_rx + 8);
        uint8_t status = PS_OK;
        bool include_samples = valid && action == PS_CMD_FRAME;
        uint16_t n;
        uint32_t rate, seq;
        xSemaphoreTake(capture_lock, portMAX_DELAY);
        n = current_n; rate = current_rate; seq = latest_seq;
        xSemaphoreGive(capture_lock);
        if (!valid) {
            status = PS_BAD_REQUEST;
        } else if (action == PS_CMD_CONFIG) {
            if (!valid_config(wanted_rate, wanted_n)) {
                status = PS_BAD_REQUEST;
            } else {
                acquire_config_t req = { wanted_rate, wanted_n };
                xQueueSend(config_req, &req, portMAX_DELAY);
                acquire_result_t got;
                if (xQueueReceive(config_reply, &got, pdMS_TO_TICKS(1500)) == pdTRUE &&
                    got.result == ESP_OK) {
                    rate = got.rate; n = got.n;
                } else {
                    status = PS_ADC_ERROR;
                }
            }
        } else if (action == PS_CMD_FRAME) {
            xSemaphoreTake(capture_lock, portMAX_DELAY);
            n = current_n; rate = current_rate; seq = latest_seq;
            if (!latest_valid) status = PS_NO_DATA;
            if (status == PS_OK) {
                /* Prepack under mutex, then transmit without blocking acquisition. */
                make_reply(PS_OK, n, rate, seq, latest[0], latest[1], true);
            }
            xSemaphoreGive(capture_lock);
        } else if (action != PS_CMD_PING) {
            status = PS_BAD_REQUEST;
        }
        if (status != PS_OK || !include_samples) {
            make_reply(status, n, rate, seq, NULL, NULL, include_samples);
        }
        const size_t length = PS_HEADER_BYTES + (include_samples ? 4 * n : 0);
        spi_slave_transaction_t response = { .length = length * 8,
                                             .tx_buffer = spi_reply, .rx_buffer = spi_reply_rx };
        ESP_ERROR_CHECK(spi_slave_transmit(SPI2_HOST, &response, portMAX_DELAY));
        /* Ensure the host can observe READY=0 before the next command setup. */
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}

void app_main(void) {
    /* WARNING: Wi-Fi and ADC2 conflict on classic ESP32; use ADC1 only here. */
    capture_lock = xSemaphoreCreateMutex();
    config_req = xQueueCreate(1, sizeof(acquire_config_t));
    config_reply = xQueueCreate(1, sizeof(acquire_result_t));
    configASSERT(capture_lock && config_req && config_reply);
    adc_continuous_handle_cfg_t adc_cfg = { .max_store_buf_size = 8192,
                                             .conv_frame_size = 256 };
    ESP_ERROR_CHECK(adc_continuous_new_handle(&adc_cfg, &adc_handle));
    xTaskCreatePinnedToCore(acquisition_task, "acquisition", 8192, NULL, 15, NULL, 1);
    xTaskCreatePinnedToCore(spi_task, "spi_slave", 6144, NULL, 12, NULL, 0);
}
