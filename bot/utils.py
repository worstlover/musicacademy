import json
import requests
import jdatetime
import re
import random
from datetime import datetime, timedelta, time

from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q, Sum

from core.models import (
    Student, Teacher, ClassSession, WalletTransaction,
    TeacherEarning, Settlement, RateTemplate, TeacherRate,
    SessionSwapRequest, AbsenceRequest
)

BALE_BOT_TOKEN = '1989571340:qMlMGrxZa47eDBuPfLd5CY6Me4MGrIjJ98U'
BALE_API_URL = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}"

WEEK_DAYS = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنج‌شنبه', 'جمعه']


def send_bale_message(chat_id, text, reply_markup=None):
    """ارسال پیام به بله"""
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(f"{BALE_API_URL}/sendMessage", json=payload, timeout=10)
        return response
    except Exception as e:
        print(f"❌ [BALE] Error: {e}")
        return None


def send_bale_photo(chat_id, photo, caption=None):
    """ارسال عکس به بله"""
    payload = {"chat_id": chat_id, "photo": photo, "caption": caption or ""}
    try:
        response = requests.post(f"{BALE_API_URL}/sendPhoto", json=payload, timeout=10)
        return response
    except Exception as e:
        print(f"❌ [PHOTO] Error: {e}")
        return None


def get_teacher_rate(teacher):
    """دریافت تعرفه ساعتی استاد (اولین تعرفه)"""
    tr = TeacherRate.objects.filter(teacher=teacher).first()
    if tr:
        return tr.hourly_rate
    return 100000


def calculate_session_fee(teacher, rate_template=None, duration_minutes=60):
    """
    محاسبه دقیق هزینه جلسه
    - اگه rate_template مشخص باشه → از همون تعرفه
    - وگرنه → از اولین تعرفه استاد
    - فرمول: (تعرفه ساعتی × مدت) ÷ ۶۰
    """
    if rate_template:
        teacher_rate = TeacherRate.objects.filter(
            teacher=teacher,
            rate_template=rate_template
        ).first()
        if teacher_rate:
            return teacher_rate.calculate_fee(duration_minutes)
    
    # تعرفه پیش‌فرض
    teacher_rate = TeacherRate.objects.filter(teacher=teacher).first()
    if teacher_rate:
        return teacher_rate.calculate_fee(duration_minutes)
    
    # حداقل مبلغ
    return 50000 * duration_minutes // 60


def get_teacher_rate_info(teacher, rate_template=None):
    """
    دریافت اطلاعات کامل تعرفه
    return: (rate_template, hourly_rate, duration_fee)
    """
    if rate_template:
        teacher_rate = TeacherRate.objects.filter(
            teacher=teacher,
            rate_template=rate_template
        ).first()
        if teacher_rate:
            return rate_template, teacher_rate.hourly_rate
    
    teacher_rate = TeacherRate.objects.filter(teacher=teacher).first()
    if teacher_rate:
        return teacher_rate.rate_template, teacher_rate.hourly_rate
    
    return None, 100000


def generate_session_code(student):
    """تولید کد جلسه یکتا"""
    student_id = str(student.id)
    random_part = str(random.randint(10000, 99999))
    code = f"{student_id}{random_part}"
    while cache.get(f"code_to_student_{code}"):
        random_part = str(random.randint(10000, 99999))
        code = f"{student_id}{random_part}"
    return code


def validate_session_code(code, student):
    """اعتبارسنجی کد جلسه"""
    student_id = str(student.id)
    if not code.startswith(student_id):
        return False, "شناسه هنرجو نادرست"
    return True, "کد معتبر"


def get_local_time(dt):
    """تبدیل به زمان محلی"""
    return timezone.localtime(dt)


def process_settlement(teacher, amount):
    """ثبت تسویه و علامت‌گذاری درآمدها"""
    earnings = TeacherEarning.objects.filter(teacher=teacher, is_settled=False).order_by('created_at')
    remaining = amount
    for earning in earnings:
        if remaining <= 0:
            break
        if earning.amount <= remaining:
            earning.is_settled = True
            earning.settled_at = timezone.now()
            earning.save()
            remaining -= earning.amount
    
    Settlement.objects.create(
        teacher=teacher, amount=amount,
        settlement_type='cash', status='paid', paid_at=timezone.now()
    )


def send_session_confirmation(student, session, teacher):
    """ارسال پیام کامل تایید جلسه به هنرجو"""
    chat_id = cache.get(f"student_chat_{student.id}")
    if not chat_id:
        return
    
    from core.models import get_random_quote
    quote = get_random_quote()
    local_dt = get_local_time(session.session_date)
    
    # ✅ رفرش هنرجو برای موجودی جدید
    student.refresh_from_db()
    
    msg = (
        f"✅ **جلسه ثبت شد**\n\n"
        f"👤 {student.get_full_name()}\n"
        f"👨‍🏫 {teacher.get_full_name()}\n"
        f"📅 {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
        f"⏱️ مدت: {session.duration_minutes} دقیقه\n"
    )
    
    # ✅ اصلاح شده: استفاده از course.rate_template
    if session.course and session.course.rate_template:
        msg += f"📋 تعرفه: {session.course.rate_template.name}\n"
    
    msg += f"💰 هزینه: {session.fee:,} تومان\n"
    msg += f"💳 کسر از حساب: {session.fee:,} تومان\n"
    msg += f"💵 مانده حساب: {student.wallet_balance:,} تومان\n\n"
    msg += f"🎵 {quote}"
    
    send_bale_message(chat_id, msg)


def refresh_student(student):
    """رفرش هنرجو از دیتابیس"""
    student.refresh_from_db()
    return student


def refresh_teacher(teacher):
    """رفرش استاد از دیتابیس"""
    teacher.refresh_from_db()
    return teacher


def get_week_dates(week_offset=0):
    """دریافت تاریخ‌های هفته با روز شمسی درست"""
    today = timezone.localtime(timezone.now()).date()
    today_jd = jdatetime.date.fromgregorian(date=today)
    days_since_saturday = today_jd.weekday()
    week_start = (today_jd - timedelta(days=days_since_saturday)).togregorian()
    week_start = week_start + timedelta(weeks=week_offset)
    
    dates = []
    for i in range(7):
        day_date = week_start + timedelta(days=i)
        jd = jdatetime.date.fromgregorian(date=day_date)
        dates.append({
            'day_index': i,
            'day_name': WEEK_DAYS[jd.weekday()],
            'date': day_date,
            'jalali': jd.strftime('%Y/%m/%d'),
            'weekday': jd.weekday(),
        })
    return dates


def check_time_conflict(teacher, date, start_time, duration_minutes, exclude_id=None):
    """چک تداخل زمانی برای یک استاد"""
    sessions = ClassSession.objects.filter(
        teacher=teacher,
        session_date__date=date,
        status__in=['pending', 'confirmed']
    )
    if exclude_id:
        sessions = sessions.exclude(id=exclude_id)
    
    new_start = time.fromisoformat(start_time)
    new_end = (datetime.combine(date, new_start) + timedelta(minutes=duration_minutes)).time()
    
    for s in sessions:
        local_dt = get_local_time(s.session_date)
        s_start = local_dt.time()
        s_end = (datetime.combine(date, s_start) + timedelta(minutes=s.duration_minutes)).time()
        if new_start < s_end and new_end > s_start:
            return True, s
    return False, None


def format_jalali_datetime(dt):
    """فرمت تاریخ شمسی"""
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime('%Y/%m/%d %H:%M')


def format_jalali_date(d):
    """فرمت تاریخ شمسی فقط تاریخ"""
    return jdatetime.date.fromgregorian(date=d).strftime('%Y/%m/%d')


def format_jalali_time(dt):
    """فرمت فقط ساعت"""
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime('%H:%M')


def notify_student(student, text, reply_markup=None):
    """ارسال پیام به هنرجو"""
    chat_id = cache.get(f"student_chat_{student.id}")
    if chat_id:
        send_bale_message(chat_id, text, reply_markup=reply_markup)
        return True
    return False


def notify_teacher(teacher, text, reply_markup=None):
    """ارسال پیام به استاد"""
    chat_id = cache.get(f"teacher_chat_{teacher.id}")
    if chat_id:
        send_bale_message(chat_id, text, reply_markup=reply_markup)
        return True
    return False


def notify_manager(text, reply_markup=None):
    """ارسال پیام به همه مدیران"""
    from django.contrib.auth.models import User
    managers = User.objects.filter(is_superuser=True)
    sent = 0
    for manager in managers:
        chat_id = cache.get(f"manager_chat_{manager.id}")
        if chat_id:
            send_bale_message(chat_id, text, reply_markup=reply_markup)
            sent += 1
    return sent


def get_student_today_session(student):
    """دریافت جلسه امروز هنرجو"""
    today = timezone.localtime(timezone.now()).date()
    return student.sessions.filter(
        session_date__date=today,
        status__in=['confirmed', 'pending']
    ).first()


def get_session_fee_details(session):
    """
    دریافت جزئیات هزینه جلسه
    return: (fee, duration, rate_template_name, hourly_rate)
    """
    fee = session.fee
    duration = session.duration_minutes
    
    # ✅ اصلاح شده: استفاده از course.rate_template
    rate_name = "پیش‌فرض"
    if session.course and session.course.rate_template:
        rate_name = session.course.rate_template.name
    
    hourly_rate = 0
    if session.course and session.course.rate_template:
        teacher_rate = TeacherRate.objects.filter(
            teacher=session.teacher,
            rate_template=session.course.rate_template
        ).first()
        if teacher_rate:
            hourly_rate = teacher_rate.hourly_rate
    else:
        teacher_rate = TeacherRate.objects.filter(teacher=session.teacher).first()
        if teacher_rate:
            hourly_rate = teacher_rate.hourly_rate
    
    return fee, duration, rate_name, hourly_rate