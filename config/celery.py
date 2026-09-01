# بالای فایل config/celery.py
from celery import Celery
from celery.schedules import crontab  # ✅ این import درسته

app = Celery('music_academy')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.conf.beat_schedule = {
    'check-daily-absences': {
        'task': 'bot.tasks.check_daily_absences',
        'schedule': crontab(hour=23, minute=30),
    },
    'check-student-balances': {
        'task': 'bot.tasks.check_student_balances',
        'schedule': 300.0,
    },
    'check-settlements-due': {
        'task': 'bot.tasks.check_settlements_due',
        'schedule': 3600.0,
    },
}