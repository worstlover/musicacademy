import jdatetime
from datetime import timedelta
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Sum, Q

from core.models import Student, Teacher, ClassSession, WalletTransaction, TeacherEarning, Settlement, RateTemplate, TeacherRate, Course
from ..utils import (
    send_bale_message, get_local_time, validate_session_code,
    calculate_session_fee, get_student_today_session, send_session_confirmation,
    notify_student
)
from ..keyboards import build_teacher_menu


WEEK_DAYS_FA = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنج‌شنبه', 'جمعه']


def get_teacher_week_dates(teacher, week_offset=0):
    """دریافت تاریخ‌های هفته با آفست"""
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
            'day_name': WEEK_DAYS_FA[jd.weekday()],
            'date': day_date,
            'jalali': jd.strftime('%Y/%m/%d'),
        })
    return dates


def build_teacher_week_keyboard(week_offset=0):
    """کیبورد ناوبری هفته برای استاد"""
    keyboard = []
    nav_row = [
        {"text": "⬅️ هفته قبل", "callback_data": f"teacher_weeknav_{week_offset - 1}"},
        {"text": "📅 این هفته", "callback_data": "teacher_weeknav_0"},
        {"text": "هفته بعد ➡️", "callback_data": f"teacher_weeknav_{week_offset + 1}"}
    ]
    keyboard.append(nav_row)
    keyboard.append([{"text": "❌ بازگشت", "callback_data": "back_to_teacher_menu"}])
    return {"inline_keyboard": keyboard}


def handle_teacher_callback(chat_id, data, teacher):
    """مدیریت callback های استاد"""
    
    if data == "code_checkin":
        cache.set(f"state_{chat_id}", {"step": "CODE_CHECKIN"}, timeout=600)
        send_bale_message(chat_id, "🔑 کد جلسه:")
    
    elif data == "today_schedule":
        today = timezone.localtime(timezone.now()).date()
        sessions = teacher.sessions.filter(session_date__date=today).order_by('session_date')
        if not sessions.exists():
            send_bale_message(chat_id, "امروز برنامه نیست.")
        else:
            msg = "📅 **برنامه امروز:**\n\n"
            jd = jdatetime.date.fromgregorian(date=today)
            msg += f"📅 {WEEK_DAYS_FA[jd.weekday()]} - {jd.strftime('%Y/%m/%d')}\n\n"
            for s in sessions:
                local_dt = get_local_time(s.session_date)
                status_emoji = {'pending': '⏳', 'confirmed': '✅', 'cancelled': '❌'}.get(s.status, '?')
                msg += f"{status_emoji} {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')} - {s.student.get_full_name()}\n"
                
                if s.course:
                    msg += f"   🎵 {s.course.name}\n"
                
                msg += f"   ⏱️ {s.duration_minutes} دقیقه | 💰 {s.fee:,}\n"
                
                if s.course and s.course.rate_template:
                    msg += f"   📋 {s.course.rate_template.name}\n"
                
                msg += f"{'─'*20}\n"
            send_bale_message(chat_id, msg, reply_markup=build_teacher_menu(teacher))
    
    elif data == "weekly_schedule":
        cache.set(f"state_{chat_id}", {"step": "TEACHER_WEEK_VIEW", "teacher_week_offset": 0}, timeout=600)
        dates = get_teacher_week_dates(teacher, 0)
        msg = "📆 **برنامه هفتگی**\n\n"
        for d in dates:
            day_sessions = teacher.sessions.filter(
                session_date__date=d['date'],
                status__in=['pending', 'confirmed']
            ).order_by('session_date')
            
            msg += f"📅 **{d['day_name']} - {d['jalali']}**\n"
            if day_sessions.exists():
                for s in day_sessions:
                    local_dt = get_local_time(s.session_date)
                    status_emoji = {'pending': '⏳', 'confirmed': '✅'}.get(s.status, '?')
                    msg += f"  {status_emoji} {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')} - {s.student.get_full_name()}\n"
                    
                    if s.course:
                        msg += f"     🎵 {s.course.name}\n"
                    
                    msg += f"     ⏱️ {s.duration_minutes}دقیقه | 💰 {s.fee:,}\n"
                    
                    if s.course and s.course.rate_template:
                        msg += f"     📋 {s.course.rate_template.name}\n"
            else:
                msg += "  —\n"
            msg += f"{'─'*20}\n"
        send_bale_message(chat_id, msg, reply_markup=build_teacher_week_keyboard(0))
    
    elif data.startswith("teacher_weeknav_"):
        week_offset = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "TEACHER_WEEK_VIEW", "teacher_week_offset": week_offset}, timeout=600)
        dates = get_teacher_week_dates(teacher, week_offset)
        msg = "📆 **برنامه هفتگی**\n\n"
        if week_offset == 0:
            msg += "📅 هفته جاری\n\n"
        elif week_offset > 0:
            msg += f"📅 {week_offset} هفته بعد\n\n"
        else:
            msg += f"📅 {abs(week_offset)} هفته قبل\n\n"
        
        for d in dates:
            day_sessions = teacher.sessions.filter(
                session_date__date=d['date'],
                status__in=['pending', 'confirmed']
            ).order_by('session_date')
            
            msg += f"📅 **{d['day_name']} - {d['jalali']}**\n"
            if day_sessions.exists():
                for s in day_sessions:
                    local_dt = get_local_time(s.session_date)
                    status_emoji = {'pending': '⏳', 'confirmed': '✅'}.get(s.status, '?')
                    msg += f"  {status_emoji} {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')} - {s.student.get_full_name()}\n"
                    
                    if s.course:
                        msg += f"     🎵 {s.course.name}\n"
                    
                    msg += f"     ⏱️ {s.duration_minutes}دقیقه | 💰 {s.fee:,}\n"
                    
                    if s.course and s.course.rate_template:
                        msg += f"     📋 {s.course.rate_template.name}\n"
            else:
                msg += "  —\n"
            msg += f"{'─'*20}\n"
        send_bale_message(chat_id, msg, reply_markup=build_teacher_week_keyboard(week_offset))
    
    elif data == "back_to_teacher_menu":
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "📋 منوی استاد:", reply_markup=build_teacher_menu(teacher))
    
    elif data == "my_income":
        teacher.refresh_from_db()
        
        # محاسبه درآمدها
        total_earned = TeacherEarning.objects.filter(teacher=teacher).aggregate(Sum('amount'))['amount__sum'] or 0
        total_settled = TeacherEarning.objects.filter(teacher=teacher, is_settled=True).aggregate(Sum('amount'))['amount__sum'] or 0
        total_pending = TeacherEarning.objects.filter(teacher=teacher, is_settled=False).aggregate(Sum('amount'))['amount__sum'] or 0
        
        # محاسبه درآمد هفته
        today = timezone.localtime(timezone.now()).date()
        today_jd = jdatetime.date.fromgregorian(date=today)
        days_since_saturday = today_jd.weekday()
        week_start = (today_jd - timedelta(days=days_since_saturday)).togregorian()
        week_end = week_start + timedelta(days=6)
        
        week_earned = TeacherEarning.objects.filter(
            teacher=teacher,
            created_at__date__gte=week_start,
            created_at__date__lte=week_end
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        # محاسبه درآمد ماه
        month_start = today.replace(day=1)
        month_earned = TeacherEarning.objects.filter(
            teacher=teacher,
            created_at__date__gte=month_start,
            created_at__date__lte=today
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        # محاسبه درآمد سال
        year_start = today.replace(month=1, day=1)
        year_earned = TeacherEarning.objects.filter(
            teacher=teacher,
            created_at__date__gte=year_start,
            created_at__date__lte=today
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        msg = f"💰 **درآمد {teacher.get_full_name()}**\n\n"
        msg += f"{'─'*30}\n"
        msg += f"📊 **کل درآمد:** {total_earned:,} تومان\n"
        msg += f"✅ **تسویه شده:** {total_settled:,} تومان\n"
        msg += f"💳 **مانده طلب:** {total_pending:,} تومان\n"
        msg += f"{'─'*30}\n\n"
        msg += f"📅 **درآمد این هفته:** {week_earned:,} تومان\n"
        msg += f"📅 **درآمد این ماه:** {month_earned:,} تومان\n"
        msg += f"📅 **درآمد امسال:** {year_earned:,} تومان\n"
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 گزارش کامل", "callback_data": "income_full_report"}],
                [{"text": "💳 درخواست تسویه", "callback_data": "settlement_request"}],
                [{"text": "❌ بازگشت", "callback_data": "back_to_teacher_menu"}]
            ]
        }
        send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data == "income_full_report":
        teacher.refresh_from_db()
        
        # آخرین 20 تراکنش درآمد
        earnings = TeacherEarning.objects.filter(teacher=teacher).order_by('-created_at')[:20]
        
        msg = f"📊 **گزارش کامل درآمد**\n\n"
        msg += f"{'─'*30}\n"
        
        for e in earnings:
            local_dt = get_local_time(e.created_at)
            date_str = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d')
            
            if e.is_settled:
                status = "✅"
            else:
                status = "⏳"
            
            msg += f"{status} {date_str}\n"
            msg += f"   👤 {e.session.student.get_full_name()}\n"
            if e.session.course:
                msg += f"   🎵 {e.session.course.name}\n"
            msg += f"   💰 {e.amount:,} تومان\n"
            msg += f"{'─'*20}\n"
        
        send_bale_message(chat_id, msg, reply_markup=build_teacher_menu(teacher))
    
    elif data == "settlement_request":
        teacher.refresh_from_db()
        pending = teacher.pending_settlement
        
        if pending <= 0:
            send_bale_message(chat_id, "✅ تمام درآمدهای شما تسویه شده است.")
        else:
            # نمایش جزئیات قبل از ثبت درخواست
            msg = f"💳 **درخواست تسویه**\n\n"
            msg += f"💰 مبلغ قابل تسویه: {pending:,} تومان\n\n"
            msg += "آیا مطمئن هستید؟\n"
            msg += "پس از ثبت درخواست، مدیر آن را بررسی و پرداخت میکند."
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ ثبت درخواست", "callback_data": "confirm_settlement"}],
                    [{"text": "❌ انصراف", "callback_data": "back_to_teacher_menu"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data == "confirm_settlement":
        teacher.refresh_from_db()
        pending = teacher.pending_settlement
        
        if pending <= 0:
            send_bale_message(chat_id, "✅ تمام درآمدهای شما تسویه شده است.")
        else:
            # چک تکراری نبودن درخواست
            existing = Settlement.objects.filter(
                teacher=teacher, 
                status='pending'
            ).first()
            
            if existing:
                send_bale_message(
                    chat_id, 
                    f"⚠️ شما یک درخواست تسویه فعال دارید:\n"
                    f"💰 مبلغ: {existing.amount:,} تومان\n"
                    f"📅 تاریخ: {existing.get_jalali_date() if hasattr(existing, 'get_jalali_date') else ''}\n\n"
                    f"لطفاً منتظر بررسی مدیر باشید."
                )
            else:
                Settlement.objects.create(
                    teacher=teacher, 
                    amount=pending, 
                    status='pending'
                )
                
                send_bale_message(
                    chat_id, 
                    f"✅ درخواست تسویه {pending:,} تومان ثبت شد.\n"
                    f"مدیر به زودی آن را بررسی میکند.",
                    reply_markup=build_teacher_menu(teacher)
                )
                
                # اطلاع به مدیر
                from django.contrib.auth.models import User
                managers = User.objects.filter(is_superuser=True)
                for manager in managers:
                    manager_chat = cache.get(f"manager_chat_{manager.id}")
                    if manager_chat:
                        send_bale_message(
                            manager_chat,
                            f"💳 درخواست تسویه جدید\n\n"
                            f"👨‍🏫 {teacher.get_full_name()}\n"
                            f"💰 مبلغ: {pending:,} تومان"
                        )
    
    elif data == "send_message_to_course":
        # نمایش کلاس‌های استاد
        courses = Course.objects.filter(teacher=teacher, is_active=True)
        
        if not courses.exists():
            send_bale_message(chat_id, "🎵 شما کلاسی ندارید.")
            return
        
        msg = "📨 **ارسال پیام به هنرجویان**\n\n"
        msg += "🎵 انتخاب کلاس:\n\n"
        
        keyboard = []
        for c in courses:
            student_count = c.enrollments.filter(is_active=True).count()
            msg += f"• {c.name} ({student_count} هنرجو)\n"
            keyboard.append([{"text": f"📨 {c.name}", "callback_data": f"teacher_msg_course_{c.id}"}])
        
        keyboard.append([{"text": "❌ بازگشت", "callback_data": "back_to_teacher_menu"}])
        send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("teacher_msg_course_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid, teacher=teacher).first()
        
        if course:
            cache.set(f"state_{chat_id}", {"step": "TEACHER_COURSE_MESSAGE", "course_id": cid}, timeout=600)
            send_bale_message(chat_id, f"📨 **پیام به هنرجویان {course.name}**\n\nمتن پیام را وارد کنید:")
    
    elif data.startswith("teacher_swap_approve_"):
        swap_id = int(data.split("_")[-1])
        from core.models import SessionSwapRequest
        swap_request = SessionSwapRequest.objects.filter(id=swap_id, status='pending').first()
        if swap_request:
            swap_request.status = 'accepted'
            swap_request.responded_at = timezone.now()
            swap_request.save()
            requester_chat = cache.get(f"student_chat_{swap_request.requesting_student.id}")
            if requester_chat:
                msg = f"✅ جابجایی توسط استاد {teacher.get_full_name()} تایید شد!"
                if swap_request.preferred_start and swap_request.preferred_end:
                    msg += f"\n⏰ {swap_request.preferred_start.strftime('%H:%M')} تا {swap_request.preferred_end.strftime('%H:%M')}"
                send_bale_message(requester_chat, msg)
            send_bale_message(chat_id, "✅", reply_markup=build_teacher_menu(teacher))
    
    elif data.startswith("teacher_swap_reject_"):
        swap_id = int(data.split("_")[-1])
        from core.models import SessionSwapRequest
        swap_request = SessionSwapRequest.objects.filter(id=swap_id, status='pending').first()
        if swap_request:
            swap_request.status = 'rejected'
            swap_request.responded_at = timezone.now()
            swap_request.save()
            requester_chat = cache.get(f"student_chat_{swap_request.requesting_student.id}")
            if requester_chat:
                send_bale_message(requester_chat, f"❌ جابجایی توسط استاد {teacher.get_full_name()} رد شد.")
            send_bale_message(chat_id, "❌", reply_markup=build_teacher_menu(teacher))


def handle_teacher_text(chat_id, text, text_en, teacher, state):
    """مدیریت پیام‌های متنی استاد"""
    step = state.get('step', '') if state else ''
    
    if step == 'CODE_CHECKIN':
        code = text_en.strip()
        student_id = cache.get(f"code_to_student_{code}")
        
        if not student_id:
            send_bale_message(chat_id, "❌ کد نامعتبر.", reply_markup=build_teacher_menu(teacher))
            cache.delete(f"state_{chat_id}")
            return
        
        student = Student.objects.filter(id=student_id).first()
        
        if not student:
            send_bale_message(chat_id, "❌ هنرجو یافت نشد.", reply_markup=build_teacher_menu(teacher))
            cache.delete(f"state_{chat_id}")
            return
        
        student.refresh_from_db()
        
        is_valid, msg = validate_session_code(code, student)
        if not is_valid:
            send_bale_message(chat_id, f"❌ {msg}", reply_markup=build_teacher_menu(teacher))
            cache.delete(f"state_{chat_id}")
            return
        
        # پیدا کردن جلسه امروز برای هزینه درست
        today_session = get_student_today_session(student)
        
        if today_session:
            fee = today_session.fee
            duration = today_session.duration_minutes
            course = today_session.course if today_session.course else None
        else:
            fee = calculate_session_fee(teacher, None, 60)
            duration = 60
            course = None
        
        # چک موجودی
        if student.wallet_balance < fee:
            send_bale_message(
                chat_id,
                f"❌ موجودی هنرجو کافی نیست.\n"
                f"💰 موجودی: {student.wallet_balance:,}\n"
                f"💳 نیاز: {fee:,}\n"
                f"⏱️ مدت: {duration} دقیقه",
                reply_markup=build_teacher_menu(teacher)
            )
            cache.delete(f"state_{chat_id}")
            return
        
        # ثبت جلسه
        session = ClassSession.objects.create(
            student=student,
            teacher=teacher,
            course=course,
            duration_minutes=duration,
            session_date=timezone.now(),
            fee=fee,
            status='confirmed',
            verification_method='code'
        )
        
        # کسر از حساب
        WalletTransaction.objects.create(
            student=student,
            transaction_type='debit',
            amount=fee,
            description=f"جلسه {duration} دقیقه‌ای با {teacher.get_full_name()}",
            status='approved',
            session=session
        )
        
        # سهم استاد
        TeacherEarning.objects.create(
            teacher=teacher,
            session=session,
            amount=teacher.calculate_teacher_share(fee)
        )
        
        cache.delete(f"code_to_student_{code}")
        cache.delete(f"student_code_{student.id}")
        cache.delete(f"state_{chat_id}")
        
        # پیام به استاد
        msg = f"✅ **جلسه ثبت شد!**\n\n"
        msg += f"👤 هنرجو: {student.get_full_name()}\n"
        
        if course:
            msg += f"🎵 کلاس: {course.name}\n"
        
        msg += f"⏱️ مدت: {duration} دقیقه\n"
        
        if course and course.rate_template:
            msg += f"📋 تعرفه: {course.rate_template.name}\n"
        
        msg += f"💰 هزینه: {fee:,} تومان\n"
        msg += f"💳 سهم شما: {teacher.calculate_teacher_share(fee):,} تومان"
        
        send_bale_message(chat_id, msg, reply_markup=build_teacher_menu(teacher))
        
        # پیام کامل به هنرجو
        send_session_confirmation(student, session, teacher)
    
    elif step == 'TEACHER_COURSE_MESSAGE':
        course = Course.objects.filter(id=state['course_id'], teacher=teacher).first()
        
        if course:
            enrollments = course.enrollments.filter(is_active=True)
            sent_count = 0
            
            for enrollment in enrollments:
                student = enrollment.student
                if notify_student(student, f"📨 **پیام از استاد {teacher.get_full_name()}**\n\n🎵 کلاس: {course.name}\n\n{text}"):
                    sent_count += 1
            
            cache.delete(f"state_{chat_id}")
            send_bale_message(
                chat_id,
                f"✅ پیام به {sent_count} هنرجو ارسال شد.",
                reply_markup=build_teacher_menu(teacher)
            )