from celery import shared_task
from django.utils import timezone
from django.core.cache import cache
from datetime import timedelta
import jdatetime

from core.models import (
    Student, Teacher, ClassSession, WalletTransaction,
    TeacherEarning, Settlement, AbsenceRequest
)


# ================= توابع کمکی =================

def send_bale_message(chat_id, text, reply_markup=None):
    """ارسال پیام به بله"""
    import requests
    from django.conf import settings
    
    BALE_BOT_TOKEN = getattr(settings, 'BALE_BOT_TOKEN', '1989571340:qMlMGrxZa47eDBuPfLd5CY6Me4MGrIjJ98U')
    BALE_API_URL = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}"
    
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(f"{BALE_API_URL}/sendMessage", json=payload, timeout=10)
        return response
    except Exception as e:
        print(f"❌ [TASK BALE] Error: {e}")
        return None


def notify_student_absence(student, session):
    """اطلاع به هنرجو برای غیبت غیرموجه"""
    chat_id = cache.get(f"student_chat_{student.id}")
    if chat_id:
        msg = (
            f"🚫 **غیبت غیرموجه ثبت شد**\n\n"
            f"👤 {student.get_full_name()}\n"
            f"📅 {session.get_jalali_date()}\n"
            f"👨‍🏫 {session.teacher.get_full_name()}\n"
            f"💰 کسر از حساب: {session.fee:,} تومان\n"
            f"💵 موجودی جدید: {student.wallet_balance:,} تومان\n\n"
            f"⚠️ برای غیبت موجه باید حداقل ۱۲ ساعت قبل درخواست بدید."
        )
        send_bale_message(chat_id, msg)


# ================= تسک‌های اصلی =================

@shared_task
def check_daily_absences():
    """
    چک غیبت‌های روزانه
    - جلسات گذشته که confirmed هستن و check_in_time ندارن
    - اگه درخواست غیبت تایید شده دارن → غیبت موجه
    - وگرنه → غیبت غیرموجه + کسر هزینه
    """
    now = timezone.now()
    
    # جلسات گذشته که هنوز confirmed هستن و check-in نشدن
    past_sessions = ClassSession.objects.filter(
        session_date__lt=now,
        status='confirmed',
        check_in_time__isnull=True
    )
    
    results = {
        'total_checked': past_sessions.count(),
        'authorized': 0,
        'unauthorized': 0,
        'errors': 0,
    }
    
    print(f"🔍 [ABSENCE CHECK] Found {past_sessions.count()} past sessions")
    
    for session in past_sessions:
        try:
            # چک درخواست غیبت تایید شده
            has_approved_absence = AbsenceRequest.objects.filter(
                student=session.student,
                session=session,
                status='approved'
            ).exists()
            
            if has_approved_absence:
                # ✅ غیبت موجه - بدون کسر
                session.status = 'cancelled'
                session.verification_method = 'absent_authorized'
                session.save()
                results['authorized'] += 1
                print(f"✅ [ABSENCE] مجاز: {session.student.get_full_name()}")
            else:
                # ❌ غیبت غیرموجه - کسر هزینه
                WalletTransaction.objects.create(
                    student=session.student,
                    transaction_type='debit',
                    amount=session.fee,
                    description=f"🚫 غیبت غیرموجه - {session.teacher.get_full_name()}",
                    status='approved',
                    session=session
                )
                
                session.status = 'cancelled'
                session.verification_method = 'absent_unauthorized'
                session.save()
                
                # رفرش هنرجو
                session.student.refresh_from_db()
                
                # اطلاع به هنرجو
                notify_student_absence(session.student, session)
                
                # چک رد لاین
                session.student.check_credit_limit()
                
                results['unauthorized'] += 1
                print(f"❌ [ABSENCE] غیرموجه: {session.student.get_full_name()} - کسر {session.fee:,}")
                
        except Exception as e:
            results['errors'] += 1
            print(f"❌ [ABSENCE ERROR] Session {session.id}: {e}")
    
    print(f"✅ [ABSENCE CHECK] مجاز: {results['authorized']}, غیرموجه: {results['unauthorized']}, خطا: {results['errors']}")
    return results


@shared_task
def check_student_balances():
    """
    چک موجودی هنرجویان
    - هشدار کم بودن موجودی
    - مسدود/رفع مسدودی بر اساس رد لاین
    """
    students = Student.objects.filter(is_active=True)
    warnings_sent = 0
    blocked = 0
    unblocked = 0
    
    for student in students:
        try:
            student.refresh_from_db()
            
            # چک رد لاین
            if student.check_credit_limit():
                blocked += 1
                # اطلاع مسدودی
                chat_id = cache.get(f"student_chat_{student.id}")
                if chat_id:
                    msg = (
                        f"🔴 **حساب شما مسدود شد**\n\n"
                        f"موجودی: {student.wallet_balance:,} تومان\n"
                        f"سقف مجاز: {student.credit_limit:,} تومان\n\n"
                        f"برای فعال‌سازی مجدد حساب خود را شارژ کنید."
                    )
                    send_bale_message(chat_id, msg)
            
            elif student.is_blocked and student.wallet_balance >= student.credit_limit:
                student.is_blocked = False
                student.blocked_at = None
                student.save()
                unblocked += 1
                # اطلاع رفع مسدودی
                chat_id = cache.get(f"student_chat_{student.id}")
                if chat_id:
                    send_bale_message(chat_id, "🟢 حساب شما فعال شد!")
            
            # هشدار کم بودن موجودی
            if not student.is_blocked and student.should_send_warning():
                chat_id = cache.get(f"student_chat_{student.id}")
                if chat_id:
                    msg = (
                        f"⚠️ **هشدار موجودی**\n\n"
                        f"موجودی: {student.wallet_balance:,} تومان\n"
                        f"هزینه جلسه: {student.last_session_fee:,} تومان\n"
                        f"جلسات باقی‌مانده: {student.remaining_sessions}\n\n"
                        f"لطفاً حساب خود را شارژ کنید."
                    )
                    send_bale_message(chat_id, msg)
                    student.last_warning_sent = timezone.now()
                    student.save()
                    warnings_sent += 1
                    
        except Exception as e:
            print(f"❌ [BALANCE] Student {student.id}: {e}")
    
    print(f"✅ [BALANCE] Warnings: {warnings_sent}, Blocked: {blocked}, Unblocked: {unblocked}")
    return {'warnings': warnings_sent, 'blocked': blocked, 'unblocked': unblocked}


@shared_task
def check_settlements_due():
    """
    چک تسویه‌های سررسید شده
    - اگه سررسید گذشته و هنوز پرداخت نشده → هشدار
    """
    settlements = Settlement.objects.filter(
        status='pending',
        due_date__lt=timezone.now().date(),
        warning_sent=False
    )
    
    sent = 0
    for settlement in settlements:
        try:
            settlement.status = 'overdue'
            settlement.save()
            
            # هشدار به استاد
            teacher_chat = cache.get(f"teacher_chat_{settlement.teacher.id}")
            if teacher_chat:
                msg = (
                    f"⏰ **سررسید تسویه**\n\n"
                    f"💰 مبلغ: {settlement.amount:,} تومان\n"
                    f"📅 سررسید: {jdatetime.date.fromgregorian(date=settlement.due_date).strftime('%Y/%m/%d')}\n"
                    f"⚠️ این تسویه به سررسید رسیده است."
                )
                send_bale_message(teacher_chat, msg)
            
            # هشدار به مدیر
            from django.contrib.auth.models import User
            managers = User.objects.filter(is_superuser=True)
            for manager in managers:
                manager_chat = cache.get(f"manager_chat_{manager.id}")
                if manager_chat:
                    send_bale_message(manager_chat, f"⏰ تسویه {settlement.teacher.get_full_name()} به سررسید رسید!")
            
            settlement.warning_sent = True
            settlement.save()
            sent += 1
            
        except Exception as e:
            print(f"❌ [SETTLEMENT] {e}")
    
    print(f"✅ [SETTLEMENT] Warnings sent: {sent}")
    return {'sent': sent}


@shared_task
def test_task():
    """تسک تست"""
    print(f"✅ Celery is working! Time: {jdatetime.datetime.now()}")
    return "OK"