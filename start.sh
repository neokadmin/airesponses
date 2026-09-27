#!/bin/bash

# 1. Crear una carpeta web temporal y un archivo index.html para UptimeRobot
mkdir -p www
echo "Bot de Musica Activo 24/7" > www/index.html

# 2. Iniciar un servidor web ultra ligero usando Python pero como comando del sistema (CLI)
# Esto corre en segundo plano (&) y escucha en el puerto que pide Render
python3 -m http.server $PORT --directory www &

# 3. Ejecutar tu bot de Discord de forma normal en primer plano
python3 music_bot.py
