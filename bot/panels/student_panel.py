import jdatetime
import re
from datetime import time, timedelta

from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q

from core.models import Student, ClassSession, WalletTransaction, SessionSwapRequest, AbsenceRequest, get_random_quote
from ..utils import (
    send_bale_message, generate_session_code, get_local_time,
    get_teacher_rate, get_student_today_session
)
from ..keyboards import build_student_menu, build_start_menu


def handle_student_callback(chat_id, data, student):
    """مدیریت callback های هنرجو"""
    
    if data == "wallet_info":
        # رفرش کامل از دیتابیس
        student.refresh_from_db()
        
        msg = f"💰 **کیف پول**\n\nموجودی: {student.wallet_balance:,} تومان\n\n"
        msg += "📋 **تراکنش‌ها:**\n\n"
        
        # تراکنش‌ها مستقیم از دیتابیس
        transactions = student.wallet_transactions.all().order_by('-created_at')[:10]
        
        for t in transactions:
            sign = "+" if t.transaction_type == 'credit' else "-"
            status_map = {
                'pending': '⏳ در انتظار تایید',
                'approved': '✅ تایید شده',
                'rejected': '❌ رد شده'
            }
            payment_map = {
                'cash': '💵 نقد',
                'check': '📝 چک',
                'credit': '⏰ نسیه',
                'card': '💳 کارت',
                'manual': '📸 دستی'
            }
            
            msg += f"{status_map.get(t.status, '?')} {sign}{t.amount:,} تومان\n"
            msg += f"💳 {payment_map.get(t.payment_method, t.payment_method)}\n"
            msg += f"📅 {t.get_jalali_date()}\n"
            msg += f"📝 {t.description}\n"
            msg += f"{'─'*20}\n"
        
        send_bale_message(chat_id, msg, reply_markup=build_student_menu(student))
    
    elif data == "charge_history":
        # رفرش
        student.refresh_from_db()
        
        charges = student.wallet_transactions.filter(transaction_type='credit').order_by('-created_at')[:20]
        if not charges.exists():
            send_bale_message(chat_id, "📋 شارژی ثبت نشده.")
        else:
            msg = "📋 **سوابق شارژ:**\n\n"
            for c in charges:
                status_map = {'pending': '⏳ در انتظار', 'approved': '✅ تایید شده', 'rejected': '❌ رد شده'}
                payment_map = {'cash': '💵 نقد', 'check': '📝 چک', 'credit': '⏰ نسیه', 'manual': '📸 دستی'}
                msg += f"💰 {c.amount:,} تومان\n"
                msg += f"📊 {status_map.get(c.status, c.status)}\n"
                msg += f"💳 {payment_map.get(c.payment_method, c.payment_method)}\n"
                msg += f"📅 {c.get_jalali_date()}\n{'─'*20}\n"
            send_bale_message(chat_id, msg, reply_markup=build_student_menu(student))
    
    elif data == "charge_wallet":
        cache.set(f"state_{chat_id}", {"step": "CHARGE_AMOUNT"}, timeout=600)
        send_bale_message(chat_id, "💰 مبلغ شارژ (تومان):")
    
    elif data == "generate_code":
        student.refresh_from_db()
        
        if student.is_blocked:
            send_bale_message(chat_id, "🔴 حساب مسدود است.")
            return
        
        # استفاده از تابع مشترک
        today_session = get_student_today_session(student)
        
        if not today_session:
            send_bale_message(chat_id, "❌ امروز کلاسی ندارید.")
            return
        
        fee = today_session.fee
        duration = today_session.duration_minutes
        
        # ✅ نمایش نام کلاس و قالب تعرفه
        course_name = today_session.course.name if today_session.course else "کلاس"
        rate_name = today_session.course.rate_template.name if today_session.course and today_session.course.rate_template else "پیش‌فرض"
        
        balance = student.wallet_balance
        
        if balance < fee:
            send_bale_message(
                chat_id,
                f"❌ موجودی کافی نیست.\n"
                f"💰 موجودی: {balance:,}\n"
                f"💳 نیاز: {fee:,}\n"
                f"⏱️ مدت: {duration} دقیقه\n"
                f"📋 تعرفه: {rate_name}"
            )
            return
        
        # حذف کد قبلی منقضی شده
        old_code = cache.get(f"student_code_{student.id}")
        if old_code and cache.get(f"code_to_student_{old_code}"):
            send_bale_message(chat_id, f"⚠️ کد فعال دارید:\n\n`{old_code}`")
            return
        elif old_code:
            cache.delete(f"student_code_{student.id}")
        
        try:
            # تولید کد جدید
            code = generate_session_code(student)
            
            # ذخیره در cache
            cache.set(f"student_code_{student.id}", code, timeout=1800)
            cache.set(f"code_to_student_{code}", student.id, timeout=1800)
            
            send_bale_message(
                chat_id,
                f"🔑 **کد جلسه:**\n\n`{code}`\n\n"
                f"👨‍🏫 {today_session.teacher.get_full_name()}\n"
                f"🎵 {course_name}\n"
                f"📋 تعرفه: {rate_name}\n"
                f"⏱️ مدت: {duration} دقیقه\n"
                f"💰 هزینه: {fee:,}\n"
                f"⏰ اعتبار: ۳۰ دقیقه"
            )
        except Exception as e:
            print(f"Error generating code: {e}")
            send_bale_message(chat_id, "❌ خطا در تولید کد. لطفاً دوباره تلاش کنید.")
    
    elif data == "my_sessions":
        # رفرش
        student.refresh_from_db()
        
        sessions = student.sessions.filter(status__in=['confirmed', 'pending']).order_by('session_date')[:15]
        if not sessions.exists():
            send_bale_message(chat_id, "📅 جلسه‌ای نیست.")
        else:
            msg = "📅 **جلسات:**\n\n"
            for s in sessions:
                local_dt = get_local_time(s.session_date)
                status_emoji = {'pending': '⏳', 'confirmed': '✅', 'cancelled': '❌'}.get(s.status, '?')
                msg += f"{status_emoji} {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                msg += f"👨‍🏫 {s.teacher.get_full_name()}\n"
                
                # ✅ نمایش نام کلاس
                if s.course:
                    msg += f"🎵 {s.course.name}\n"
                
                msg += f"⏱️ {s.duration_minutes} دقیقه | 💰 {s.fee:,}\n"
                
                # ✅ نمایش قالب تعرفه
                if s.course and s.course.rate_template:
                    msg += f"📋 {s.course.rate_template.name}\n"
                
                msg += f"{'─'*20}\n"
            send_bale_message(chat_id, msg, reply_markup=build_student_menu(student))
    
    elif data == "swap_request":
        # رفرش
        student.refresh_from_db()
        
        upcoming = student.sessions.filter(
            status__in=['confirmed', 'pending'],
            session_date__gte=timezone.now()
        ).order_by('session_date')[:10]
        
        if not upcoming.exists():
            send_bale_message(chat_id, "❌ جلسه آینده ندارید.")
        else:
            keyboard = []
            for s in upcoming:
                local_dt = get_local_time(s.session_date)
                label = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')
                if s.course:
                    label += f" - {s.course.name}"
                keyboard.append([{"text": label, "callback_data": f"swap_select_{s.id}"}])
            
            msg = "🔄 **کدوم جلسه؟**\n\n"
            for s in upcoming:
                local_dt = get_local_time(s.session_date)
                msg += f"• {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}"
                if s.course:
                    msg += f" - {s.course.name}"
                msg += "\n"
            
            send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("swap_select_"):
        session_id = int(data.split("_")[-1])
        current_session = ClassSession.objects.filter(id=session_id, student=student).first()
        
        if current_session:
            time_diff = current_session.session_date - timezone.now()
            if time_diff.total_seconds() < 12 * 3600:
                send_bale_message(chat_id, "❌ کمتر از ۱۲ ساعت مانده.")
            else:
                cache.set(f"state_{chat_id}", {"step": "SWAP_START_TIME", "current_session_id": current_session.id}, timeout=600)
                send_bale_message(chat_id, "🔄 از چه ساعتی می‌توانید؟ (مثال: 10:00):")
    
    elif data == "absence_request":
        # رفرش
        student.refresh_from_db()
        
        upcoming = student.sessions.filter(
            status__in=['confirmed', 'pending'],
            session_date__gte=timezone.now()
        ).order_by('session_date')[:10]
        
        if not upcoming.exists():
            send_bale_message(chat_id, "❌ جلسه آینده ندارید.")
        else:
            keyboard = []
            for s in upcoming:
                local_dt = get_local_time(s.session_date)
                label = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')
                if s.course:
                    label += f" - {s.course.name}"
                keyboard.append([{"text": label, "callback_data": f"absence_select_{s.id}"}])
            
            msg = "🏠 **کدوم جلسه؟**\n\n"
            for s in upcoming:
                local_dt = get_local_time(s.session_date)
                msg += f"• {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}"
                if s.course:
                    msg += f" - {s.course.name}"
                msg += "\n"
            
            send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("absence_select_"):
        session_id = int(data.split("_")[-1])
        session = ClassSession.objects.filter(id=session_id, student=student).first()
        
        if session:
            time_diff = session.session_date - timezone.now()
            if time_diff.total_seconds() < 12 * 3600:
                send_bale_message(chat_id, "❌ کمتر از ۱۲ ساعت مانده.")
            else:
                cache.set(f"state_{chat_id}", {"step": "ABSENCE_REASON", "session_id": session.id}, timeout=600)
                send_bale_message(chat_id, "📝 دلیل غیبت:")
    
    # ========== لیست جابجایی‌ها ==========
    elif data == "swap_list":
        # رفرش
        student.refresh_from_db()
        
        swaps = SessionSwapRequest.objects.filter(
            Q(requesting_student=student) | Q(target_student=student)
        ).order_by('-created_at')[:20]
        
        if not swaps.exists():
            send_bale_message(chat_id, "🔄 درخواست جابجایی ندارید.")
        else:
            msg = "🔄 **درخواست‌های جابجایی:**\n\n"
            for sw in swaps:
                status_map = {
                    'pending': '⏳ در انتظار',
                    'accepted': '✅ تایید شده',
                    'rejected': '❌ رد شده',
                    'expired': '⏰ منقضی'
                }
                
                is_requester = sw.requesting_student == student
                other = sw.target_student if is_requester else sw.requesting_student
                
                msg += f"{status_map.get(sw.status, '?')}\n"
                if is_requester:
                    msg += f"شما درخواست دادید"
                else:
                    msg += f"درخواست به شما"
                
                if other:
                    msg += f" با {other.get_full_name()}\n"
                
                if sw.current_session:
                    local_dt = get_local_time(sw.current_session.session_date)
                    msg += f"📅 {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                    if sw.current_session.course:
                        msg += f"🎵 {sw.current_session.course.name}\n"
                
                if sw.preferred_start and sw.preferred_end:
                    msg += f"⏰ بازه: {sw.preferred_start.strftime('%H:%M')} تا {sw.preferred_end.strftime('%H:%M')}\n"
                
                msg += f"{'─'*20}\n"
            
            send_bale_message(chat_id, msg, reply_markup=build_student_menu(student))
    
    # ========== لیست غیبت‌ها ==========
    elif data == "absence_list":
        # رفرش
        student.refresh_from_db()
        
        absences = student.absence_requests.all().order_by('-created_at')[:20]
        
        if not absences.exists():
            send_bale_message(chat_id, "🏠 غیبتی ثبت نکردید.")
        else:
            msg = "🏠 **درخواست‌های غیبت:**\n\n"
            for a in absences:
                status_map = {
                    'pending': '⏳ در انتظار',
                    'approved': '✅ تایید شده',
                    'rejected': '❌ رد شده'
                }
                
                msg += f"{status_map.get(a.status, '?')}\n"
                msg += f"📝 {a.reason[:40]}\n"
                
                if a.session:
                    local_dt = get_local_time(a.session.session_date)
                    msg += f"📅 {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                    if a.session.course:
                        msg += f"🎵 {a.session.course.name}\n"
                
                msg += f"{'─'*20}\n"
            
            send_bale_message(chat_id, msg, reply_markup=build_student_menu(student))
    
    # ========== تایید جابجایی ==========
    elif data.startswith("swap_accept_"):
        swap_id = int(data.split("_")[-1])
        swap_request = SessionSwapRequest.objects.filter(
            id=swap_id, status='pending', target_student=student
        ).first()
        
        if swap_request:
            swap_request.status = 'accepted'
            swap_request.responded_at = timezone.now()
            swap_request.save()
            
            current_session = swap_request.current_session
            target_session = swap_request.target_session
            
            if target_session:
                current_old = get_local_time(current_session.session_date)
                target_old = get_local_time(target_session.session_date)
                
                temp_date = current_session.session_date
                current_session.session_date = target_session.session_date
                target_session.session_date = temp_date
                current_session.save()
                target_session.save()
                
                current_new = get_local_time(current_session.session_date)
                target_new = get_local_time(target_session.session_date)
                
                requester = swap_request.requesting_student
                target = student
                
                # پیام به درخواست‌دهنده
                requester_chat = cache.get(f"student_chat_{requester.id}")
                if requester_chat:
                    msg = (
                        f"✅ **جابجایی تایید شد**\n\n"
                        f"👤 شما: {requester.get_full_name()}\n"
                        f"👤 {target.get_full_name()}\n\n"
                        f"📅 جلسه شما:\n"
                        f"⏰ از: {jdatetime.datetime.fromgregorian(datetime=current_old).strftime('%Y/%m/%d %H:%M')}\n"
                        f"⏰ به: {jdatetime.datetime.fromgregorian(datetime=current_new).strftime('%Y/%m/%d %H:%M')}\n"
                    )
                    if current_session.course:
                        msg += f"🎵 {current_session.course.name}\n"
                    msg += f"👨‍🏫 {current_session.teacher.get_full_name()}\n\n"
                    msg += f"🎵 {get_random_quote()}"
                    send_bale_message(requester_chat, msg)
                
                # پیام به تاییدکننده
                msg = (
                    f"✅ **جابجایی تایید شد**\n\n"
                    f"👤 شما: {target.get_full_name()}\n"
                    f"👤 {requester.get_full_name()}\n\n"
                    f"📅 جلسه شما:\n"
                    f"⏰ از: {jdatetime.datetime.fromgregorian(datetime=target_old).strftime('%Y/%m/%d %H:%M')}\n"
                    f"⏰ به: {jdatetime.datetime.fromgregorian(datetime=target_new).strftime('%Y/%m/%d %H:%M')}\n"
                )
                if target_session.course:
                    msg += f"🎵 {target_session.course.name}\n"
                msg += f"👨‍🏫 {current_session.teacher.get_full_name()}\n\n"
                msg += f"🎵 {get_random_quote()}"
                send_bale_message(chat_id, msg)
                
                # پیام به استاد
                teacher_chat = cache.get(f"teacher_chat_{current_session.teacher.id}")
                if teacher_chat:
                    msg = (
                        f"🔄 **جابجایی انجام شد**\n\n"
                        f"👤 {requester.get_full_name()}\n"
                        f"⏰ {jdatetime.datetime.fromgregorian(datetime=current_old).strftime('%H:%M')} → {jdatetime.datetime.fromgregorian(datetime=current_new).strftime('%H:%M')}\n\n"
                        f"👤 {target.get_full_name()}\n"
                        f"⏰ {jdatetime.datetime.fromgregorian(datetime=target_old).strftime('%H:%M')} → {jdatetime.datetime.fromgregorian(datetime=target_new).strftime('%H:%M')}"
                    )
                    send_bale_message(teacher_chat, msg)
    
    elif data.startswith("swap_reject_"):
        swap_id = int(data.split("_")[-1])
        swap_request = SessionSwapRequest.objects.filter(
            id=swap_id, status='pending', target_student=student
        ).first()
        
        if swap_request:
            swap_request.status = 'rejected'
            swap_request.responded_at = timezone.now()
            swap_request.save()
            
            send_bale_message(chat_id, f"❌ درخواست را رد کردید.")
            
            requester_chat = cache.get(f"student_chat_{swap_request.requesting_student.id}")
            if requester_chat:
                local_dt = get_local_time(swap_request.current_session.session_date)
                msg = (
                    f"❌ **جابجایی رد شد**\n\n"
                    f"{student.get_full_name()} درخواست شما را رد کرد.\n"
                    f"📅 جلسه: {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}"
                )
                send_bale_message(requester_chat, msg)
    
    elif data == "blocked_info":
        send_bale_message(chat_id, "🔴 حساب شما مسدود است.")


def handle_student_text(chat_id, text, text_en, student, state):
    """مدیریت پیام‌های متنی هنرجو"""
    step = state.get('step', '') if state else ''
    
    if step == 'CHARGE_AMOUNT':
        if text_en.isdigit():
            state['amount'] = int(text_en)
            state['step'] = 'CHARGE_RECEIPT'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📸 عکس رسید:")
        else:
            send_bale_message(chat_id, "❌ فقط عدد:")
    
    elif step == 'SWAP_START_TIME':
        try:
            if ':' not in text:
                send_bale_message(chat_id, "❌ فرمت: 10:00")
                return
            
            parts = text.split(':')
            if len(parts) != 2:
                send_bale_message(chat_id, "❌ فرمت: 10:00")
                return
            
            h = int(parts[0].strip())
            m = int(parts[1].strip())
            
            if h < 0 or h > 23 or m < 0 or m > 59:
                send_bale_message(chat_id, "❌ ساعت نامعتبر")
                return
            
            state['start_time'] = f"{h:02d}:{m:02d}"
            state['step'] = 'SWAP_END_TIME'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "🔄 تا چه ساعتی؟ (مثال: 13:00):")
        except:
            send_bale_message(chat_id, "❌ فرمت: 10:00")
    
    elif step == 'SWAP_END_TIME':
        try:
            if ':' not in text:
                send_bale_message(chat_id, "❌ فرمت: 13:00")
                return
            
            parts = text.split(':')
            if len(parts) != 2:
                send_bale_message(chat_id, "❌ فرمت: 13:00")
                return
            
            h = int(parts[0].strip())
            m = int(parts[1].strip())
            
            if h < 0 or h > 23 or m < 0 or m > 59:
                send_bale_message(chat_id, "❌ ساعت نامعتبر")
                return
            
            end_time = time(h, m)
            current_session = ClassSession.objects.get(id=state['current_session_id'])
            
            start_parts = state['start_time'].split(':')
            start_t = time(int(start_parts[0]), int(start_parts[1]))
            
            matching = ClassSession.objects.filter(
                teacher=current_session.teacher,
                status__in=['confirmed', 'pending'],
                session_date__gte=timezone.now()
            ).exclude(student=current_session.student)
            
            matched = []
            for s in matching:
                local_t = get_local_time(s.session_date).time()
                if start_t <= local_t <= end_time:
                    matched.append(s)
            
            cache.delete(f"state_{chat_id}")
            
            if matched:
                for target in matched:
                    swap_req = SessionSwapRequest.objects.create(
                        requesting_student=current_session.student,
                        current_session=current_session,
                        target_session=target,
                        target_student=target.student,
                        preferred_start=start_t,
                        preferred_end=end_time,
                        preferred_times=[state['start_time'], f"{h:02d}:{m:02d}"]
                    )
                    
                    target_chat = cache.get(f"student_chat_{target.student.id}")
                    if target_chat:
                        keyboard = {
                            "inline_keyboard": [
                                [{"text": "✅ قبول", "callback_data": f"swap_accept_{swap_req.id}"}],
                                [{"text": "❌ رد", "callback_data": f"swap_reject_{swap_req.id}"}]
                            ]
                        }
                        
                        local_dt_current = get_local_time(current_session.session_date)
                        local_dt_target = get_local_time(target.session_date)
                        
                        msg = (
                            f"🔄 **درخواست جابجایی**\n\n"
                            f"{current_session.student.get_full_name()} میخواد جابجا بشه.\n\n"
                            f"کلاس شما: {jdatetime.datetime.fromgregorian(datetime=local_dt_target).strftime('%Y/%m/%d %H:%M')}\n"
                            f"کلاس ایشان: {jdatetime.datetime.fromgregorian(datetime=local_dt_current).strftime('%Y/%m/%d %H:%M')}\n\n"
                            f"موافق هستید؟"
                        )
                        send_bale_message(target_chat, msg, reply_markup=keyboard)
                
                send_bale_message(
                    chat_id,
                    f"✅ درخواست به {len(matched)} هنرجو ارسال شد.",
                    reply_markup=build_student_menu(current_session.student)
                )
            else:
                swap_req = SessionSwapRequest.objects.create(
                    requesting_student=current_session.student,
                    current_session=current_session,
                    target_student=None,
                    target_session=None,
                    preferred_start=start_t,
                    preferred_end=end_time,
                    preferred_times=[state['start_time'], f"{h:02d}:{m:02d}"]
                )
                
                teacher_chat = cache.get(f"teacher_chat_{current_session.teacher.id}")
                if teacher_chat:
                    local_dt = get_local_time(current_session.session_date)
                    msg = (
                        f"🔄 **درخواست جابجایی**\n\n"
                        f"👤 {current_session.student.get_full_name()}\n"
                        f"📅 کلاس: {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                        f"⏰ بازه: {state['start_time']} تا {h:02d}:{m:02d}\n"
                        f"ساعت خالی است."
                    )
                    keyboard = {
                        "inline_keyboard": [
                            [{"text": "✅ تایید", "callback_data": f"teacher_swap_approve_{swap_req.id}"}],
                            [{"text": "❌ رد", "callback_data": f"teacher_swap_reject_{swap_req.id}"}]
                        ]
                    }
                    send_bale_message(teacher_chat, msg, reply_markup=keyboard)
                
                from django.contrib.auth.models import User
                managers = User.objects.filter(is_superuser=True)
                for manager in managers:
                    manager_chat = cache.get(f"manager_chat_{manager.id}")
                    if manager_chat:
                        msg = (
                            f"🔄 **درخواست جابجایی**\n\n"
                            f"👤 {current_session.student.get_full_name()}\n"
                            f"⏰ بازه: {state['start_time']} تا {h:02d}:{m:02d}"
                        )
                        keyboard = {
                            "inline_keyboard": [
                                [{"text": "✅ تایید", "callback_data": f"manager_swap_approve_{swap_req.id}"}],
                                [{"text": "❌ رد", "callback_data": f"manager_swap_reject_{swap_req.id}"}]
                            ]
                        }
                        send_bale_message(manager_chat, msg, reply_markup=keyboard)
                
                send_bale_message(
                    chat_id,
                    "✅ ساعت خالی است. به استاد و مدیر اطلاع داده شد.",
                    reply_markup=build_student_menu(current_session.student)
                )
        except Exception as e:
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, f"❌ خطا: {e}")
    
    elif step == 'ABSENCE_REASON':
        session = ClassSession.objects.get(id=state['session_id'])
        AbsenceRequest.objects.create(
            student=student,
            session=session,
            reason=text
        )
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "✅ ثبت شد.", reply_markup=build_student_menu(student))