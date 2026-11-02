#!/bin/sh
# Render PORT o'zgaruvchisini nginx sozlamasiga qo'yadi va barcha xizmatlarni ishga tushiradi
export PORT="${PORT:-10000}"
envsubst '${PORT}' < /etc/nginx/templates/ecocalc.conf.template > /etc/nginx/conf.d/default.conf
exec supervisord -c /etc/supervisor/supervisord.conf
