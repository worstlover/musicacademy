#!/usr/bin/env bash

python -m bot.polling &
BOT_PID=$!

gunicorn config.wsgi:application --bind 0.0.0.0:$PORT &
WEB_PID=$!

trap "kill $BOT_PID $WEB_PID" SIGTERM SIGINT

wait -n $BOT_PID $WEB_PID