import requests
import json
from django.conf import settings


BALE_BOT_TOKEN = settings.BALE_BOT_TOKEN
BALE_API_URL = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/"

def send_bale_message(chat_id, text, reply_markup=None):
    url = BALE_API_URL + "sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def notify_targets(targets, message_text, exception_chat_id=None):
    """ارسال پیام گروهی به لیستی از کاربران"""
    for target in targets:
        chat_id = target.bale_chat_id
        if chat_id and chat_id != exception_chat_id:
            send_bale_message(chat_id, message_text)

# --- منوها ---
def build_start_menu():
    return {
        "keyboard": [
            [{"text": "ارسال شماره تماس 📱", "request_contact": True}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def build_student_menu():
    return {
        "inline_keyboard": [
            [{"text": "ثبت‌نام در کلاس جدید", "callback_data": "enroll_class"}],
            [{"text": "برنامه کلاسی من", "callback_data": "my_schedule"}],
            [{"text": "کیف پول و مالی", "callback_data": "wallet_info"}],
            [{"text": "خروج", "callback_data": "logout"}]
        ]
    }

def build_teacher_menu():
    return {
        "inline_keyboard": [
            [{"text": "برنامه کلاس‌های من", "callback_data": "teacher_schedule"}],
            [{"text": "ثبت حضور و غیاب", "callback_data": "teacher_attendance"}],
            [{"text": "مالی و تسویه‌حساب", "callback_data": "teacher_financial"}],
            [{"text": "خروج", "callback_data": "logout"}]
        ]
    }

def build_manager_menu():
    return {
        "inline_keyboard": [
            [{"text": "مدیریت هنرجویان", "callback_data": "manage_students"}, {"text": "مدیریت اساتید", "callback_data": "manage_teachers"}],
            [{"text": "برنامه‌ریزی هفتگی", "callback_data": "weekly_planning"}],
            [{"text": "تسویه حساب اساتید", "callback_data": "settle_teacher"}],
            [{"text": "خروج", "callback_data": "logout"}]
        ]
    }
