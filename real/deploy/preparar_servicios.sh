#!/usr/bin/env bash
# Ejecutar en Raspberry Pi con sudo, desde la carpeta descomprimida.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Uso: sudo bash real/deploy/preparar_servicios.sh"; exit 1; fi
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
USER_ORIGINAL="${SUDO_USER:-$(id -un)}"
DEST=/opt/dashboard_osciloscopio
apt-get update
apt-get install -y nginx python3-spidev python3-rpi.gpio
mkdir -p "$DEST"
cp -a "$DIR/." "$DEST/"
chown -R "$USER_ORIGINAL":"$USER_ORIGINAL" "$DEST"
for pair in pulsescope-api pulsescope-spi; do
  sed "s#User=pi#User=${USER_ORIGINAL}#g" \
    "$DEST/real/deploy/${pair}.service.example" > "/etc/systemd/system/${pair}.service"
done
# root e index.html se sirven desde esta ruta; el backend solo escucha loopback.
cp "$DEST/deploy/nginx.conf.example" /etc/nginx/sites-available/pulsescope
ln -sfn /etc/nginx/sites-available/pulsescope /etc/nginx/sites-enabled/pulsescope
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now pulsescope-api.service
systemctl enable --now nginx.service
cat <<DONE
Se prepararon Nginx y API. AUN NO se activa el servicio SPI.
1) Confirmar placa M5Stack, ADC, conexiones de 3.3V, GPIO READY, GND comun.
2) Habilitar SPI en raspi-config (reiniciar) y flashear ESP32.
3) Probar: cd $DEST/real/raspberry && python3 probar_spi_fisico.py
4) Activar: sudo systemctl enable --now pulsescope-spi.service
5) Consultar errores: sudo journalctl -u pulsescope-spi -f
6) En otro dispositivo: http://IP_DE_RASPBERRY/
DONE
