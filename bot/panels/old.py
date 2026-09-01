import jdatetime
import re
from datetime import datetime, timedelta, time

from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q, Sum

from core.models import (
    Student, Teacher, ClassSession, WalletTransaction,
    TeacherEarning, Settlement, RateTemplate, TeacherRate,
    AbsenceRequest, StudentCourse
)
from ..utils import (
    send_bale_message, send_bale_photo, get_local_time,
    process_settlement, get_teacher_rate
)
from ..keyboards import build_manager_menu


# ================= اصلاح روز هفته شمسی =================

WEEK_DAYS_FA = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنج‌شنبه', 'جمعه']


def get_week_dates(week_offset=0):
    """
    دریافت تاریخ‌های هفته با روز درست شمسی
    jdatetime.weekday(): 0=Saturday(شنبه), 6=Friday(جمعه)
    """
    today = timezone.localtime(timezone.now()).date()
    
    # تبدیل به شمسی
    today_jd = jdatetime.date.fromgregorian(date=today)
    
    # پیدا کردن شنبه این هفته (weekday=0 یعنی شنبه)
    days_since_saturday = today_jd.weekday()
    week_start_jd = today_jd - timedelta(days=days_since_saturday)
    week_start = week_start_jd.togregorian()
    
    # اعمال آفست هفته
    week_start = week_start + timedelta(weeks=week_offset)
    
    dates = []
    for i in range(7):
        day_date = week_start + timedelta(days=i)
        jd = jdatetime.date.fromgregorian(date=day_date)
        
        # روز هفته شمسی (0=شنبه)
        weekday_index = jd.weekday()
        day_name = WEEK_DAYS_FA[weekday_index]
        
        dates.append({
            'day_index': i,
            'day_name': day_name,
            'date': day_date,
            'jalali': jd.strftime('%Y/%m/%d'),
            'weekday': weekday_index,
        })
    
    return dates


def build_week_keyboard(week_offset=0):
    """کیبورد انتخاب روز با تاریخ درست"""
    dates = get_week_dates(week_offset)
    
    keyboard = []
    row = []
    for d in dates:
        label = f"{d['day_name']} {d['jalali']}"
        row.append({"text": label, "callback_data": f"planday_{d['day_index']}_{week_offset}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    nav_row = []
    nav_row.append({"text": "⬅️ قبلی", "callback_data": f"weeknav_{week_offset - 1}"})
    nav_row.append({"text": "📅 امروز", "callback_data": "weeknav_0"})
    nav_row.append({"text": "بعدی ➡️", "callback_data": f"weeknav_{week_offset + 1}"})
    keyboard.append(nav_row)
    
    keyboard.append([{"text": "❌ بازگشت", "callback_data": "back_to_manager"}])
    
    return {"inline_keyboard": keyboard}


def get_teacher_schedule(teacher, date):
    """برنامه استاد در یک روز"""
    return ClassSession.objects.filter(
        teacher=teacher,
        session_date__date=date,
        status__in=['pending', 'confirmed']
    ).order_by('session_date')


def build_day_schedule_keyboard(teacher, date):
    """کیبورد برنامه روز"""
    sessions = get_teacher_schedule(teacher, date)
    
    keyboard = []
    for s in sessions:
        local_dt = get_local_time(s.session_date)
        time_str = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')
        label = f"{time_str} - {s.student.get_full_name()}"
        keyboard.append([{"text": label, "callback_data": f"session_detail_{s.id}"}])
    
    keyboard.append([{"text": "➕ افزودن", "callback_data": f"add_session_{teacher.id}_{date.strftime('%Y-%m-%d')}"}])
    keyboard.append([{"text": "📋 کپی برنامه", "callback_data": f"copy_sched_{teacher.id}_{date.strftime('%Y-%m-%d')}"}])
    keyboard.append([{"text": "❌ بازگشت", "callback_data": f"teacher_sched_{teacher.id}"}])
    
    return {"inline_keyboard": keyboard}


def check_time_conflict(teacher, date, start_time, duration_minutes, exclude_id=None):
    """چک تداخل زمانی"""
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


def copy_schedule(teacher, source_date, target_weeks):
    """کپی برنامه به هفته‌های بعد"""
    source_sessions = get_teacher_schedule(teacher, source_date)
    
    if not source_sessions.exists():
        return 0, ["برنامه‌ای برای کپی نیست"]
    
    copied = 0
    errors = []
    
    for week in target_weeks:
        target_date = source_date + timedelta(weeks=week)
        
        for s in source_sessions:
            local_dt = get_local_time(s.session_date)
            start_time = local_dt.time()
            
            conflict, _ = check_time_conflict(
                teacher, target_date, start_time.strftime('%H:%M'), s.duration_minutes
            )
            
            if conflict:
                errors.append(f"تداخل: {target_date} - {s.student.get_full_name()}")
            else:
                new_dt = timezone.make_aware(datetime.combine(target_date, start_time))
                ClassSession.objects.create(
                    student=s.student,
                    teacher=teacher,
                    duration_minutes=s.duration_minutes,
                    session_date=new_dt,
                    fee=s.fee,
                    status='pending'
                )
                copied += 1
    
    return copied, errors


# ================= جزئیات کامل هنرجو =================

def get_student_full_details(student):
    """جزئیات کامل هنرجو"""
    msg = f"👤 **{student.get_full_name()}**\n\n"
    
    # اطلاعات شخصی
    msg += "📋 **اطلاعات شخصی:**\n"
    msg += f"📱 موبایل: {student.phone_number or 'ندارد'}\n"
    msg += f"👨‍👩‍👦 والدین: {student.parent_name or 'ندارد'}\n"
    msg += f"📱 تلفن والدین: {student.parent_phone or 'ندارد'}\n"
    msg += f"🆔 کد ملی: {student.national_code or 'ندارد'}\n"
    
    if student.birth_date:
        jd = jdatetime.date.fromgregorian(date=student.birth_date)
        msg += f"🎂 تولد: {jd.strftime('%Y/%m/%d')}\n"
    
    if student.address:
        msg += f"📍 آدرس: {student.address[:50]}\n"
    
    msg += f"\n{'─'*30}\n\n"
    
    # وضعیت مالی
    msg += "💰 **وضعیت مالی:**\n"
    msg += f"موجودی فعلی: {student.wallet_balance:,} تومان\n"
    msg += f"رد لاین: {student.credit_limit:,} تومان\n"
    
    total_credit = student.wallet_transactions.filter(
        transaction_type='credit', status='approved'
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    total_debit = student.wallet_transactions.filter(
        transaction_type='debit', status='approved'
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
    msg += f"کل شارژ: {total_credit:,} تومان\n"
    msg += f"کل کسر: {total_debit:,} تومان\n"
    
    msg += f"\n{'─'*30}\n\n"
    
    # وضعیت حساب
    status = "🔴 مسدود" if student.is_blocked else "🟢 آزاد"
    active = "🟢 فعال" if student.is_active else "⚪ غیرفعال"
    msg += f"🔐 **وضعیت حساب:**\n"
    msg += f"مسدودی: {status}\n"
    msg += f"فعالیت: {active}\n"
    
    msg += f"\n{'─'*30}\n\n"
    
    # کلاس‌ها
    enrollments = student.enrollments.filter(is_active=True)
    if enrollments.exists():
        msg += "🎵 **کلاس‌ها:**\n"
        for e in enrollments:
            course = e.course
            msg += f"• {course.name}\n"
            msg += f"  👨‍🏫 {course.teacher.get_full_name()}\n"
            if course.rate_template:
                msg += f"  📋 {course.rate_template.name}\n"
            msg += f"  💰 {course.calculate_fee():,} تومان/جلسه\n"
            msg += f"  ⏱️ {course.duration_minutes} دقیقه\n"
    else:
        msg += "🎵 **کلاس‌ها:** ندارد\n"
    
    msg += f"\n{'─'*30}\n\n"
    
    # جلسات اخیر
    recent_sessions = student.sessions.filter(status='confirmed').order_by('-session_date')[:5]
    if recent_sessions.exists():
        msg += "📅 **آخرین جلسات:**\n"
        for s in recent_sessions:
            local_dt = get_local_time(s.session_date)
            msg += f"• {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
            msg += f"  {s.teacher.get_full_name()} - {s.fee:,} تومان\n"
    
    msg += f"\n{'─'*30}\n\n"
    
    # آمار
    total_sessions = student.sessions.filter(status='confirmed').count()
    absences = student.absence_requests.filter(status='approved').count()
    swaps = student.swap_requests_sent.filter(status='accepted').count()
    
    msg += "📊 **آمار:**\n"
    msg += f"📅 جلسات: {total_sessions}\n"
    msg += f"🏠 غیبت مجاز: {absences}\n"
    msg += f"🔄 جابجایی: {swaps}\n"
    
    return msg


def build_student_detail_keyboard(student):
    """کیبورد کامل هنرجو"""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔴 مسدود" if not student.is_blocked else "🟢 آزاد", 
                 "callback_data": f"student_block_{student.id}" if not student.is_blocked else f"student_unblock_{student.id}"},
                {"text": "⚪ غیرفعال" if student.is_active else "🟢 فعال",
                 "callback_data": f"student_deactivate_{student.id}" if student.is_active else f"student_activate_{student.id}"}
            ],
            [
                {"text": "✏️ ویرایش", "callback_data": f"student_edit_{student.id}"},
                {"text": "👨‍👩‍👦 والدین", "callback_data": f"student_parent_{student.id}"}
            ],
            [
                {"text": "💰 شارژ", "callback_data": f"student_charge_{student.id}"},
                {"text": "📊 گزارش مالی", "callback_data": f"student_fin_{student.id}"}
            ],
            [
                {"text": "📅 جلسات", "callback_data": f"student_sessions_{student.id}"},
                {"text": "🏠 غیبت‌ها", "callback_data": f"student_absences_{student.id}"}
            ],
            [
                {"text": "🗑️ حذف", "callback_data": f"student_del_{student.id}"},
                {"text": "❌ بازگشت", "callback_data": "manage_students"}
            ]
        ]
    }
    return keyboard


# ================= CALLBACK =================

def handle_manager_callback(chat_id, data, state):
    
    # ================= مدیریت هنرجویان =================
    if data == "manage_students":
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ ثبت هنرجو", "callback_data": "add_student"}],
                [{"text": "🔍 جستجو", "callback_data": "search_student"}],
                [{"text": "❌ بازگشت", "callback_data": "back_to_manager"}]
            ]
        }
        send_bale_message(chat_id, "👤 مدیریت هنرجویان:", reply_markup=keyboard)
    
    elif data == "search_student":
        cache.set(f"state_{chat_id}", {"step": "SEARCH_STUDENT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام یا شماره هنرجو:")
    
    elif data == "add_student":
        cache.set(f"state_{chat_id}", {"step": "ADD_STUDENT_NAME"}, timeout=600)
        send_bale_message(chat_id, "👤 نام هنرجو:")
    
    # ================= مدیریت اساتید =================
    elif data == "manage_teachers":
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ ثبت استاد", "callback_data": "add_teacher"}],
                [{"text": "🔍 جستجو", "callback_data": "search_teacher"}],
                [{"text": "❌ بازگشت", "callback_data": "back_to_manager"}]
            ]
        }
        send_bale_message(chat_id, "👨‍🏫 مدیریت اساتید:", reply_markup=keyboard)
    
    elif data == "search_teacher":
        cache.set(f"state_{chat_id}", {"step": "SEARCH_TEACHER"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام یا شماره استاد:")
    
    elif data == "add_teacher":
        cache.set(f"state_{chat_id}", {"step": "ADD_TEACHER_NAME"}, timeout=600)
        send_bale_message(chat_id, "👨‍🏫 نام استاد:")
    
    # ================= برنامه‌ریزی =================
    elif data == "weekly_planning":
        cache.set(f"state_{chat_id}", {"step": "PLAN_SELECT_TEACHER"}, timeout=600)
        send_bale_message(chat_id, "👨‍🏫 نام استاد برای برنامه‌ریزی:")
    
    elif data.startswith("weeknav_"):
        week_offset = int(data.split("_")[1])
        if state and state.get('teacher_id'):
            teacher = Teacher.objects.filter(id=state['teacher_id']).first()
            if teacher:
                state['week_offset'] = week_offset
                state['step'] = 'PLAN_DAY_SELECT'
                cache.set(f"state_{chat_id}", state, timeout=600)
                
                dates = get_week_dates(week_offset)
                msg = f"👨‍🏫 {teacher.get_full_name()}\n\n📅 انتخاب روز:\n\n"
                for d in dates:
                    msg += f"• {d['day_name']} - {d['jalali']}\n"
                
                send_bale_message(chat_id, msg, reply_markup=build_week_keyboard(week_offset))
    
    elif data.startswith("planday_"):
        parts = data.split("_")
        day_index = int(parts[1])
        week_offset = int(parts[2])
        
        if state and state.get('teacher_id'):
            teacher = Teacher.objects.filter(id=state['teacher_id']).first()
            if teacher:
                dates = get_week_dates(week_offset)
                selected_date = dates[day_index]['date']
                correct_day_name = dates[day_index]['day_name']
                
                state['selected_date'] = selected_date.strftime('%Y-%m-%d')
                state['day_of_week'] = day_index
                state['week_offset'] = week_offset
                state['step'] = 'PLAN_DAY_SELECT'
                cache.set(f"state_{chat_id}", state, timeout=600)
                
                sessions = get_teacher_schedule(teacher, selected_date)
                jd = jdatetime.date.fromgregorian(date=selected_date)
                
                msg = f"👨‍🏫 {teacher.get_full_name()}\n"
                msg += f"📅 {correct_day_name} - {jd.strftime('%Y/%m/%d')}\n\n"
                
                if sessions.exists():
                    msg += "📋 برنامه:\n"
                    for s in sessions:
                        local_dt = get_local_time(s.session_date)
                        t = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')
                        msg += f"• {t} - {s.student.get_full_name()} ({s.duration_minutes}دقیقه)\n"
                else:
                    msg += "برنامه‌ای نیست.\n"
                
                send_bale_message(chat_id, msg, reply_markup=build_day_schedule_keyboard(teacher, selected_date))
    
    elif data.startswith("teacher_sched_"):
        tid = int(data.split("_")[-1])
        teacher = Teacher.objects.filter(id=tid).first()
        if teacher:
            state = {"step": "PLAN_DAY_SELECT", "teacher_id": tid, "week_offset": 0}
            cache.set(f"state_{chat_id}", state, timeout=600)
            
            dates = get_week_dates(0)
            msg = f"👨‍🏫 {teacher.get_full_name()}\n\n📅 انتخاب روز:\n\n"
            for d in dates:
                msg += f"• {d['day_name']} - {d['jalali']}\n"
            
            send_bale_message(chat_id, msg, reply_markup=build_week_keyboard(0))
    
    # ================= کپی برنامه =================
    elif data.startswith("copy_sched_"):
        parts = data.split("_")
        tid = int(parts[2])
        date_str = parts[3]
        
        cache.set(f"state_{chat_id}", {
            "step": "COPY_WEEKS",
            "teacher_id": tid,
            "source_date": date_str
        }, timeout=600)
        
        send_bale_message(chat_id, "📋 به چند هفته بعد کپی شود؟\n(مثال: 1 یا 1,2,3 یا 1-4)")
    
    # ================= افزودن جلسه =================
    elif data.startswith("add_session_"):
        parts = data.split("_")
        tid = int(parts[2])
        date_str = parts[3]
        
        cache.set(f"state_{chat_id}", {
            "step": "ADD_SESSION_STUDENT",
            "teacher_id": tid,
            "session_date": date_str
        }, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو:")
    
    # ================= جزئیات جلسه =================
    elif data.startswith("session_detail_"):
        sid = int(data.split("_")[-1])
        session = ClassSession.objects.filter(id=sid).first()
        if session:
            local_dt = get_local_time(session.session_date)
            msg = f"📋 جلسه\n\n"
            msg += f"👤 {session.student.get_full_name()}\n"
            msg += f"👨‍🏫 {session.teacher.get_full_name()}\n"
            msg += f"📅 {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
            msg += f"⏱️ {session.duration_minutes} دقیقه\n"
            msg += f"💰 {session.fee:,} تومان\n"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✏️ ساعت", "callback_data": f"edit_time_{sid}"}],
                    [{"text": "⏱️ مدت", "callback_data": f"edit_dur_{sid}"}],
                    [{"text": "🗑️ حذف", "callback_data": f"del_sess_{sid}"}],
                    [{"text": "❌ بازگشت", "callback_data": f"teacher_sched_{session.teacher.id}"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("edit_time_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_SESSION_TIME", "session_id": sid}, timeout=600)
        send_bale_message(chat_id, "⏰ ساعت جدید (14:00):")
    
    elif data.startswith("edit_dur_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_SESSION_DURATION", "session_id": sid}, timeout=600)
        send_bale_message(chat_id, "⏱️ مدت (دقیقه):")
    
    elif data.startswith("del_sess_"):
        sid = int(data.split("_")[-1])
        session = ClassSession.objects.filter(id=sid).first()
        if session:
            session.delete()
            send_bale_message(chat_id, "🗑️ حذف شد.", reply_markup=build_manager_menu())
    
    # ================= غیبت‌ها =================
    elif data == "absence_requests":
        absences = AbsenceRequest.objects.filter(status='pending')
        if not absences.exists():
            send_bale_message(chat_id, "🏠 درخواستی نیست.", reply_markup=build_manager_menu())
        else:
            for a in absences:
                local_dt = get_local_time(a.session.session_date)
                msg = f"🏠 {a.student.get_full_name()}\n"
                msg += f"📅 {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                msg += f"📝 {a.reason}\n"
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "✅ تایید", "callback_data": f"absence_approve_{a.id}"},
                         {"text": "❌ رد", "callback_data": f"absence_reject_{a.id}"}]
                    ]
                }
                send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("absence_approve_"):
        aid = int(data.split("_")[-1])
        a = AbsenceRequest.objects.filter(id=aid, status='pending').first()
        if a:
            a.status = 'approved'
            a.approved_at = timezone.now()
            a.save()
            a.session.status = 'cancelled'
            a.session.save()
            sc = cache.get(f"student_chat_{a.student.id}")
            if sc:
                send_bale_message(sc, "✅ غیبت شما تایید شد. هزینه کسر نمی‌شود.")
            send_bale_message(chat_id, "✅ تایید شد.", reply_markup=build_manager_menu())
    
    elif data.startswith("absence_reject_"):
        aid = int(data.split("_")[-1])
        a = AbsenceRequest.objects.filter(id=aid, status='pending').first()
        if a:
            a.status = 'rejected'
            a.save()
            sc = cache.get(f"student_chat_{a.student.id}")
            if sc:
                send_bale_message(sc, "❌ غیبت شما رد شد.")
            send_bale_message(chat_id, "❌ رد شد.", reply_markup=build_manager_menu())
    
    # ================= شارژها =================
    elif data == "pending_charges":
        pending = WalletTransaction.objects.filter(
            transaction_type='credit', status='pending'
        )[:10]
        
        if not pending.exists():
            send_bale_message(chat_id, "✅ شارژی نیست.", reply_markup=build_manager_menu())
        else:
            for t in pending:
                msg = f"👤 {t.student.get_full_name()}\n"
                msg += f"💰 {t.amount:,} تومان\n"
                msg += f"📅 {t.get_jalali_date()}\n"
                msg += f"💳 نوع: {t.payment_method}\n"
                
                if t.receipt_image:
                    send_bale_photo(chat_id, t.receipt_image, msg)
                else:
                    send_bale_message(chat_id, msg + "\n⚠️ بدون عکس رسید")
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "✅ تایید", "callback_data": f"approve_charge_{t.id}"},
                         {"text": "❌ رد", "callback_data": f"reject_charge_{t.id}"}]
                    ]
                }
                send_bale_message(chat_id, "تصمیم شما:", reply_markup=keyboard)
    
    elif data.startswith("approve_charge_"):
        tid = int(data.split("_")[-1])
        t = WalletTransaction.objects.filter(id=tid, status='pending').first()
        if t:
            t.status = 'approved'
            t.save()
            sc = cache.get(f"student_chat_{t.student.id}")
            if sc:
                send_bale_message(sc, f"✅ شارژ {t.amount:,} تایید شد!")
            send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("reject_charge_"):
        tid = int(data.split("_")[-1])
        t = WalletTransaction.objects.filter(id=tid, status='pending').first()
        if t:
            t.status = 'rejected'
            t.save()
            sc = cache.get(f"student_chat_{t.student.id}")
            if sc:
                send_bale_message(sc, f"❌ شارژ {t.amount:,} رد شد.")
            send_bale_message(chat_id, "❌", reply_markup=build_manager_menu())
    
    # ================= تنظیمات =================
    elif data == "set_warning":
        cache.set(f"state_{chat_id}", {"step": "WARNING_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو برای تنظیم هشدار:")
    
    elif data == "set_credit_limit":
        cache.set(f"state_{chat_id}", {"step": "CREDIT_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو برای تنظیم رد لاین:")
    
    elif data == "settle_teacher":
        cache.set(f"state_{chat_id}", {"step": "SETTLE_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام استاد برای تسویه:")
    
    elif data == "financial_report":
        cache.set(f"state_{chat_id}", {"step": "FINANCE_START"}, timeout=600)
        send_bale_message(chat_id, "📅 از تاریخ (1403/06/01):")
    
    # ================= جزئیات هنرجو =================
    elif data.startswith("student_detail_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            msg = get_student_full_details(s)
            send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
    
    elif data.startswith("student_sessions_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            sessions = s.sessions.filter(status__in=['confirmed', 'pending']).order_by('session_date')[:20]
            if not sessions.exists():
                send_bale_message(chat_id, "📅 جلسه‌ای نیست.")
            else:
                msg = f"📅 **جلسات {s.get_full_name()}**\n\n"
                for sess in sessions:
                    local_dt = get_local_time(sess.session_date)
                    status_emoji = {'pending': '⏳', 'confirmed': '✅', 'cancelled': '❌'}.get(sess.status, '?')
                    msg += f"{status_emoji} {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                    msg += f"   {sess.teacher.get_full_name()} - {sess.fee:,} تومان\n{'─'*20}\n"
                
                keyboard = {"inline_keyboard": [[{"text": "❌ بازگشت", "callback_data": f"student_detail_{s.id}"}]]}
                send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("student_absences_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            absences = s.absence_requests.all().order_by('-created_at')[:20]
            if not absences.exists():
                send_bale_message(chat_id, "🏠 غیبتی نیست.")
            else:
                msg = f"🏠 **غیبت‌های {s.get_full_name()}**\n\n"
                for a in absences:
                    status_map = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
                    msg += f"{status_map.get(a.status, '?')} {a.reason[:40]}\n"
                    msg += f"   📅 {jdatetime.datetime.fromgregorian(datetime=a.created_at).strftime('%Y/%m/%d')}\n{'─'*20}\n"
                
                keyboard = {"inline_keyboard": [[{"text": "❌ بازگشت", "callback_data": f"student_detail_{s.id}"}]]}
                send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("student_swaps_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            swaps = SessionSwapRequest.objects.filter(
                Q(requesting_student=s) | Q(target_student=s)
            ).order_by('-created_at')[:20]
            
            if not swaps.exists():
                send_bale_message(chat_id, "🔄 جابجایی‌ای نیست.")
            else:
                msg = f"🔄 **جابجایی‌های {s.get_full_name()}**\n\n"
                for sw in swaps:
                    status_map = {'pending': '⏳', 'accepted': '✅', 'rejected': '❌', 'expired': '⏰'}
                    is_requester = sw.requesting_student == s
                    other = sw.target_student if is_requester else sw.requesting_student
                    
                    msg += f"{status_map.get(sw.status, '?')} "
                    msg += "درخواست" if is_requester else "دریافت"
                    if other:
                        msg += f" با {other.get_full_name()}"
                    msg += f"\n📅 {jdatetime.datetime.fromgregorian(datetime=sw.created_at).strftime('%Y/%m/%d')}\n{'─'*20}\n"
                
                keyboard = {"inline_keyboard": [[{"text": "❌ بازگشت", "callback_data": f"student_detail_{s.id}"}]]}
                send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("student_parent_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_PARENT_NAME", "student_id": sid}, timeout=600)
        send_bale_message(chat_id, "👨‍👩‍👦 نام والدین:")
    
    elif data.startswith("student_block_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_blocked = True
            s.save()
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("student_unblock_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_blocked = False
            s.save()
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("student_deactivate_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_active = False
            s.save()
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("student_activate_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_active = True
            s.save()
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("student_del_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.delete()
        send_bale_message(chat_id, "🗑️", reply_markup=build_manager_menu())
    
    elif data.startswith("student_edit_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_STUDENT_NAME", "student_id": sid}, timeout=600)
        send_bale_message(chat_id, "✏️ نام:")
    
    elif data.startswith("student_charge_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "CHARGE_TYPE", "student_id": sid}, timeout=600)
        keyboard = {
            "inline_keyboard": [
                [{"text": "💵 نقد", "callback_data": "stype_cash"}],
                [{"text": "📝 چک", "callback_data": "stype_check"}],
                [{"text": "⏰ نسیه", "callback_data": "stype_credit"}]
            ]
        }
        send_bale_message(chat_id, "📋 نوع:", reply_markup=keyboard)
    
    elif data.startswith("student_fin_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "STUDENT_FINANCE_START", "student_id": sid}, timeout=600)
        send_bale_message(chat_id, "📅 از تاریخ:")
    
    elif data.startswith("stype_"):
        stype_map = {'stype_cash': 'cash', 'stype_check': 'check', 'stype_credit': 'credit'}
        state = state or {}
        state['charge_type'] = stype_map[data]
        state['step'] = 'CHARGE_AMOUNT'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "💰 مبلغ:")
    
    # ================= جزئیات استاد =================
    elif data.startswith("teacher_detail_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            msg = f"👨‍🏫 **{t.get_full_name()}**\n\n"
            msg += f"📱 {t.phone_number}\n"
            msg += f"🎵 {t.specialization}\n"
            msg += f"💯 {t.commission_percent}%\n"
            msg += f"💰 طلبکار: {t.pending_settlement:,}\n\n"
            msg += "📋 تعرفه‌ها:\n"
            for tr in t.rates.all():
                msg += f"• {tr.rate_template.name}: {tr.hourly_rate:,} تومان/ساعت\n"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📅 برنامه", "callback_data": f"teacher_sched_{t.id}"}],
                    [{"text": "📋 تعرفه‌ها", "callback_data": f"teacher_rates_{t.id}"}],
                    [{"text": "💯 درصد", "callback_data": f"teacher_comm_{t.id}"}],
                    [{"text": "📊 گزارش", "callback_data": f"teacher_fin_{t.id}"}],
                    [{"text": "❌ بازگشت", "callback_data": "manage_teachers"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("teacher_rates_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            rates = RateTemplate.objects.filter(is_active=True)
            keyboard = []
            for r in rates:
                keyboard.append([{"text": r.name, "callback_data": f"setrate_{tid}_{r.id}"}])
            keyboard.append([{"text": "➕ جدید", "callback_data": f"newrate_{tid}"}])
            keyboard.append([{"text": "❌ بازگشت", "callback_data": f"teacher_detail_{tid}"}])
            send_bale_message(chat_id, "📋 تعرفه‌ها:", reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("setrate_"):
        parts = data.split("_")
        tid = int(parts[1])
        rid = int(parts[2])
        cache.set(f"state_{chat_id}", {"step": "SET_RATE", "teacher_id": tid, "rate_id": rid}, timeout=600)
        send_bale_message(chat_id, "💰 مبلغ:")
    
    elif data.startswith("newrate_"):
        tid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "NEW_RATE_NAME", "teacher_id": tid}, timeout=600)
        send_bale_message(chat_id, "📋 نام:")
    
    elif data.startswith("teacher_comm_"):
        tid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_COMMISSION", "teacher_id": tid}, timeout=600)
        send_bale_message(chat_id, "💯 درصد:")
    
    elif data.startswith("teacher_fin_"):
        tid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "TEACHER_FINANCE_START", "teacher_id": tid}, timeout=600)
        send_bale_message(chat_id, "📅 از تاریخ:")
    
    # ================= تایید/رد جابجایی توسط مدیر =================
    elif data.startswith("manager_swap_approve_"):
        swap_id = int(data.split("_")[-1])
        swap_request = SessionSwapRequest.objects.filter(id=swap_id, status='pending').first()
        
        if swap_request:
            swap_request.status = 'accepted'
            swap_request.responded_at = timezone.now()
            swap_request.save()
            
            requester = swap_request.requesting_student
            requester_chat = cache.get(f"student_chat_{requester.id}")
            if requester_chat:
                local_dt = get_local_time(swap_request.current_session.session_date)
                msg = (
                    f"✅ **جابجایی تایید شد**\n\n"
                    f"📅 جلسه شما: {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                )
                if swap_request.preferred_start and swap_request.preferred_end:
                    msg += f"⏰ بازه جدید: {swap_request.preferred_start.strftime('%H:%M')} تا {swap_request.preferred_end.strftime('%H:%M')}\n"
                msg += f"\nلطفاً برای زمان دقیق با استاد هماهنگ کنید."
                send_bale_message(requester_chat, msg)
            
            teacher_chat = cache.get(f"teacher_chat_{swap_request.current_session.teacher.id}")
            if teacher_chat:
                send_bale_message(teacher_chat, f"✅ جابجایی {requester.get_full_name()} توسط مدیر تایید شد.")
            
            send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("manager_swap_reject_"):
        swap_id = int(data.split("_")[-1])
        swap_request = SessionSwapRequest.objects.filter(id=swap_id, status='pending').first()
        
        if swap_request:
            swap_request.status = 'rejected'
            swap_request.responded_at = timezone.now()
            swap_request.save()
            
            requester_chat = cache.get(f"student_chat_{swap_request.requesting_student.id}")
            if requester_chat:
                send_bale_message(requester_chat, "❌ جابجایی توسط مدیر رد شد.")
            
            send_bale_message(chat_id, "❌", reply_markup=build_manager_menu())

# ================= TEXT =================

def handle_manager_text(chat_id, text, text_en, state):
    step = state.get('step', '') if state else ''
    
    # ================= ویرایش والدین =================
    if step == 'EDIT_PARENT_NAME':
        s = Student.objects.filter(id=state['student_id']).first()
        if s:
            s.parent_name = text if text else None
            s.save()
        state['step'] = 'EDIT_PARENT_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱 تلفن والدین:")
    
    elif step == 'EDIT_PARENT_PHONE':
        s = Student.objects.filter(id=state['student_id']).first()
        if s:
            if re.match(r'^09\d{9}$', text_en):
                s.parent_phone = text_en
            else:
                s.parent_phone = text if text else None
            s.save()
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= جستجو =================
    elif step == 'SEARCH_STUDENT':
        students = Student.objects.filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text) | Q(phone_number__icontains=text_en)
        )[:10]
        cache.delete(f"state_{chat_id}")
        
        if not students.exists():
            send_bale_message(chat_id, "❌", reply_markup=build_manager_menu())
        else:
            keyboard = []
            for s in students:
                keyboard.append([{"text": s.get_full_name(), "callback_data": f"student_detail_{s.id}"}])
            keyboard.append([{"text": "❌", "callback_data": "manage_students"}])
            send_bale_message(chat_id, "نتایج:", reply_markup={"inline_keyboard": keyboard})
    
    elif step == 'SEARCH_TEACHER':
        teachers = Teacher.objects.filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text) | Q(phone_number__icontains=text_en)
        )[:10]
        cache.delete(f"state_{chat_id}")
        
        if not teachers.exists():
            send_bale_message(chat_id, "❌", reply_markup=build_manager_menu())
        else:
            keyboard = []
            for t in teachers:
                keyboard.append([{"text": t.get_full_name(), "callback_data": f"teacher_detail_{t.id}"}])
            keyboard.append([{"text": "❌", "callback_data": "manage_teachers"}])
            send_bale_message(chat_id, "نتایج:", reply_markup={"inline_keyboard": keyboard})
    
    # ================= ثبت هنرجو =================
    elif step == 'ADD_STUDENT_NAME':
        state['first_name'] = text
        state['step'] = 'ADD_STUDENT_LAST'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "نام خانوادگی:")
    
    elif step == 'ADD_STUDENT_LAST':
        state['last_name'] = text
        state['step'] = 'ADD_STUDENT_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱:")
    
    elif step == 'ADD_STUDENT_PHONE':
        if re.match(r'^09\d{9}$', text_en):
            state['phone'] = text_en
            state['step'] = 'ADD_STUDENT_PARENT_NAME'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "👨‍👩‍👦 والدین:")
        else:
            send_bale_message(chat_id, "❌")
    
    elif step == 'ADD_STUDENT_PARENT_NAME':
        state['parent_name'] = text or None
        state['step'] = 'ADD_STUDENT_PARENT_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱 والدین:")
    
    elif step == 'ADD_STUDENT_PARENT_PHONE':
        Student.objects.create(
            first_name=state['first_name'],
            last_name=state['last_name'],
            phone_number=state['phone'],
            parent_name=state.get('parent_name'),
            parent_phone=text or None
        )
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= ثبت استاد =================
    elif step == 'ADD_TEACHER_NAME':
        state['first_name'] = text
        state['step'] = 'ADD_TEACHER_LAST'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "نام خانوادگی:")
    
    elif step == 'ADD_TEACHER_LAST':
        state['last_name'] = text
        state['step'] = 'ADD_TEACHER_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱:")
    
    elif step == 'ADD_TEACHER_PHONE':
        if re.match(r'^09\d{9}$', text_en):
            state['phone'] = text_en
            state['step'] = 'ADD_TEACHER_SPECIALTY'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "🎵 تخصص:")
    
    elif step == 'ADD_TEACHER_SPECIALTY':
        Teacher.objects.create(
            first_name=state['first_name'],
            last_name=state['last_name'],
            phone_number=state['phone'],
            specialization=text
        )
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= کپی برنامه =================
    elif step == 'COPY_WEEKS':
        teacher = Teacher.objects.get(id=state['teacher_id'])
        source_date = datetime.strptime(state['source_date'], '%Y-%m-%d').date()
        
        weeks = []
        t = text_en.strip()
        if '-' in t:
            start, end = map(int, t.split('-'))
            weeks = list(range(start, end + 1))
        elif ',' in t:
            weeks = [int(w.strip()) for w in t.split(',') if w.strip().isdigit()]
        elif t.isdigit():
            weeks = [int(t)]
        
        if not weeks:
            send_bale_message(chat_id, "❌")
            return
        
        copied, errors = copy_schedule(teacher, source_date, weeks)
        cache.delete(f"state_{chat_id}")
        
        msg = f"✅ {copied} جلسه کپی شد"
        if errors:
            msg += f"\n⚠️ {len(errors)} تداخل"
        send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
    
    # ================= افزودن جلسه =================
    elif step == 'ADD_SESSION_STUDENT':
        students = Student.objects.filter(Q(first_name__icontains=text) | Q(last_name__icontains=text))[:5]
        if students.exists():
            state['students_list'] = list(students.values_list('id', flat=True))
            state['step'] = 'ADD_SESSION_STUDENT_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            msg = ""
            for i, s in enumerate(students, 1):
                msg += f"{i}. {s.get_full_name()}\n"
            send_bale_message(chat_id, msg + "\nشماره:")
    
    elif step == 'ADD_SESSION_STUDENT_NUM':
        try:
            idx = int(text_en) - 1
            state['student_id'] = state['students_list'][idx]
            state['step'] = 'ADD_SESSION_TIME'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "⏰ (14:00):")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'ADD_SESSION_TIME':
        try:
            h, m = map(int, text.split(':'))
            state['start_time'] = f"{h:02d}:{m:02d}"
            state['step'] = 'ADD_SESSION_DURATION'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "⏱️:")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'ADD_SESSION_DURATION':
        if text_en.isdigit():
            duration = int(text_en)
            teacher = Teacher.objects.get(id=state['teacher_id'])
            student = Student.objects.get(id=state['student_id'])
            date_obj = datetime.strptime(state['session_date'], '%Y-%m-%d').date()
            
            conflict, _ = check_time_conflict(teacher, date_obj, state['start_time'], duration)
            
            if conflict:
                send_bale_message(chat_id, "❌ تداخل!")
            else:
                fee = get_teacher_rate(teacher) * duration // 60
                dt = timezone.make_aware(datetime.combine(date_obj, time.fromisoformat(state['start_time'])))
                ClassSession.objects.create(
                    student=student, teacher=teacher,
                    duration_minutes=duration, session_date=dt,
                    fee=fee, status='pending'
                )
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= ویرایش جلسه =================
    elif step == 'EDIT_SESSION_TIME':
        try:
            h, m = map(int, text.split(':'))
            session = ClassSession.objects.get(id=state['session_id'])
            cur = get_local_time(session.session_date)
            session.session_date = timezone.make_aware(datetime.combine(cur.date(), time(h, m)))
            session.save()
        except:
            pass
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif step == 'EDIT_SESSION_DURATION':
        if text_en.isdigit():
            session = ClassSession.objects.get(id=state['session_id'])
            session.duration_minutes = int(text_en)
            session.fee = get_teacher_rate(session.teacher) * int(text_en) // 60
            session.save()
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= برنامه‌ریزی =================
    elif step == 'PLAN_SELECT_TEACHER':
        teachers = Teacher.objects.filter(Q(first_name__icontains=text) | Q(last_name__icontains=text))[:5]
        if teachers.exists():
            state['teachers_list'] = list(teachers.values_list('id', flat=True))
            state['step'] = 'PLAN_SELECT_TEACHER_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            msg = ""
            for i, t in enumerate(teachers, 1):
                msg += f"{i}. {t.get_full_name()}\n"
            send_bale_message(chat_id, msg + "\nشماره:")
    
    elif step == 'PLAN_SELECT_TEACHER_NUM':
        try:
            idx = int(text_en) - 1
            state['teacher_id'] = state['teachers_list'][idx]
            state['step'] = 'PLAN_DAY_SELECT'
            state['week_offset'] = 0
            cache.set(f"state_{chat_id}", state, timeout=600)
            
            dates = get_week_dates(0)
            msg = "📅 روز:\n\n"
            for d in dates:
                msg += f"• {d['day_name']} - {d['jalali']}\n"
            
            send_bale_message(chat_id, msg, reply_markup=build_week_keyboard(0))
        except:
            send_bale_message(chat_id, "❌")
    
    # ================= شارژ =================
    elif step == 'CHARGE_AMOUNT':
        if text_en.isdigit():
            student = Student.objects.get(id=state['student_id'])
            ct = state.get('charge_type', 'cash')
            if ct in ['check', 'credit']:
                state['amount'] = int(text_en)
                state['step'] = 'CHARGE_DUE'
                cache.set(f"state_{chat_id}", state, timeout=600)
                send_bale_message(chat_id, "📅 سررسید:")
            else:
                WalletTransaction.objects.create(
                    student=student, transaction_type='credit',
                    amount=int(text_en), description=f"شارژ {ct}",
                    status='approved', payment_method=ct
                )
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif step == 'CHARGE_DUE':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            student = Student.objects.get(id=state['student_id'])
            WalletTransaction.objects.create(
                student=student, transaction_type='credit',
                amount=state['amount'], description=f"شارژ - سررسید {text}",
                status='approved', payment_method=state.get('charge_type')
            )
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")
    
    # ================= تسویه =================
    elif step == 'SETTLE_SELECT':
        teachers = Teacher.objects.filter(Q(first_name__icontains=text) | Q(last_name__icontains=text))[:5]
        if teachers.exists():
            state['teachers_list'] = list(teachers.values_list('id', flat=True))
            state['step'] = 'SETTLE_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            msg = ""
            for i, t in enumerate(teachers, 1):
                msg += f"{i}. {t.get_full_name()} (طلب: {t.pending_settlement:,})\n"
            send_bale_message(chat_id, msg + "\nشماره:")
    
    elif step == 'SETTLE_NUM':
        try:
            idx = int(text_en) - 1
            state['teacher_id'] = state['teachers_list'][idx]
            state['step'] = 'SETTLE_AMOUNT'
            cache.set(f"state_{chat_id}", state, timeout=600)
            t = Teacher.objects.get(id=state['teacher_id'])
            send_bale_message(chat_id, f"💰 (طلب: {t.pending_settlement:,}):")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'SETTLE_AMOUNT':
        if text_en.isdigit():
            teacher = Teacher.objects.get(id=state['teacher_id'])
            amount = int(text_en)
            if amount > teacher.pending_settlement:
                send_bale_message(chat_id, "❌ بیشتر از طلب")
            else:
                process_settlement(teacher, amount)
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= تعرفه =================
    elif step == 'SET_RATE':
        if text_en.isdigit():
            teacher = Teacher.objects.get(id=state['teacher_id'])
            rate = RateTemplate.objects.get(id=state['rate_id'])
            TeacherRate.objects.update_or_create(
                teacher=teacher, rate_template=rate,
                defaults={'hourly_rate': int(text_en)}
            )
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif step == 'NEW_RATE_NAME':
        state['rate_name'] = text
        state['step'] = 'NEW_RATE_AMOUNT'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "💰:")
    
    elif step == 'NEW_RATE_AMOUNT':
        if text_en.isdigit():
            rate = RateTemplate.objects.create(name=state['rate_name'])
            TeacherRate.objects.create(
                teacher_id=state['teacher_id'],
                rate_template=rate,
                hourly_rate=int(text_en)
            )
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif step == 'EDIT_COMMISSION':
        if text_en.isdigit() and int(text_en) <= 100:
            t = Teacher.objects.get(id=state['teacher_id'])
            t.commission_percent = int(text_en)
            t.save()
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= ویرایش هنرجو =================
    elif step == 'EDIT_STUDENT_NAME':
        s = Student.objects.get(id=state['student_id'])
        parts = text.split(' ')
        s.first_name = parts[0]
        s.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
        s.save()
        state['step'] = 'EDIT_STUDENT_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱:")
    
    elif step == 'EDIT_STUDENT_PHONE':
        s = Student.objects.get(id=state['student_id'])
        if re.match(r'^09\d{9}$', text_en):
            s.phone_number = text_en
            s.save()
        state['step'] = 'EDIT_STUDENT_PARENT'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "👨‍👩‍👦:")
    
    elif step == 'EDIT_STUDENT_PARENT':
        s = Student.objects.get(id=state['student_id'])
        s.parent_name = text or None
        s.save()
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= هشدار و ردلاین =================
    elif step == 'WARNING_SELECT':
        students = Student.objects.filter(Q(first_name__icontains=text) | Q(last_name__icontains=text))[:5]
        if students.exists():
            state['students_list'] = list(students.values_list('id', flat=True))
            state['step'] = 'WARNING_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            msg = ""
            for i, s in enumerate(students, 1):
                msg += f"{i}. {s.get_full_name()}\n"
            send_bale_message(chat_id, msg + "\nشماره:")
    
    elif step == 'WARNING_NUM':
        try:
            idx = int(text_en) - 1
            state['student_id'] = state['students_list'][idx]
            state['step'] = 'WARNING_INTERVAL'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "⏰:")
        except:
            pass
    
    elif step == 'WARNING_INTERVAL':
        if text_en.isdigit():
            s = Student.objects.get(id=state['student_id'])
            s.warning_interval_hours = int(text_en)
            s.save()
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif step == 'CREDIT_SELECT':
        students = Student.objects.filter(Q(first_name__icontains=text) | Q(last_name__icontains=text))[:5]
        if students.exists():
            state['students_list'] = list(students.values_list('id', flat=True))
            state['step'] = 'CREDIT_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            msg = ""
            for i, s in enumerate(students, 1):
                msg += f"{i}. {s.get_full_name()}\n"
            send_bale_message(chat_id, msg + "\nشماره:")
    
    elif step == 'CREDIT_NUM':
        try:
            idx = int(text_en) - 1
            state['student_id'] = state['students_list'][idx]
            state['step'] = 'CREDIT_AMOUNT'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "🚫:")
        except:
            pass
    
    elif step == 'CREDIT_AMOUNT':
        try:
            s = Student.objects.get(id=state['student_id'])
            s.credit_limit = int(text_en)
            s.save()
        except:
            pass
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    # ================= گزارش مالی =================
    elif step == 'FINANCE_START':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            state['start_date'] = jd.togregorian()
            state['step'] = 'FINANCE_END'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📅 تا:")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'FINANCE_END':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            end_date = jd.togregorian()
            
            revenue = WalletTransaction.objects.filter(
                transaction_type='credit', status='approved',
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum'] or 0
            
            debit = WalletTransaction.objects.filter(
                transaction_type='debit', status='approved',
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum'] or 0
            
            msg = f"📊 شارژ: {revenue:,}\n💳 کسر: {debit:,}\n📈 تراز: {revenue-debit:,}"
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")
    
    # ================= گزارش هنرجو =================
    elif step == 'STUDENT_FINANCE_START':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            state['start_date'] = jd.togregorian()
            state['step'] = 'STUDENT_FINANCE_END'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📅 تا:")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'STUDENT_FINANCE_END':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            end_date = jd.togregorian()
            
            student = Student.objects.get(id=state['student_id'])
            transactions = student.wallet_transactions.filter(
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            )
            
            msg = f"📊 {student.get_full_name()}\n\n"
            for t in transactions:
                sign = "+" if t.transaction_type == 'credit' else "-"
                msg += f"{sign}{t.amount:,} - {t.description}\n"
            
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")
    
    # ================= گزارش استاد =================
    elif step == 'TEACHER_FINANCE_START':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            state['start_date'] = jd.togregorian()
            state['step'] = 'TEACHER_FINANCE_END'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📅 تا:")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'TEACHER_FINANCE_END':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            end_date = jd.togregorian()
            
            teacher = Teacher.objects.get(id=state['teacher_id'])
            earnings = TeacherEarning.objects.filter(
                teacher=teacher,
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            )
            
            msg = f"📊 {teacher.get_full_name()}\n\n"
            total = 0
            for e in earnings:
                msg += f"💰 {e.amount:,} - {e.session.student.get_full_name()}\n"
                total += e.amount
            
            msg += f"\n💵 مجموع: {total:,}"
            
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")