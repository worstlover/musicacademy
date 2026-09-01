import jdatetime
import re
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q, Sum

from core.models import Student, ClassSession, SessionSwapRequest, AbsenceRequest
from ...utils import send_bale_message, get_local_time
from ...keyboards import build_manager_menu, build_student_detail_keyboard


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


def handle_student_callback(chat_id, data, state):
    """مدیریت callback های هنرجو در پنل مدیر"""
    
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
        send_bale_message(chat_id, "🔍 نام یا شماره:")
    
    elif data == "add_student":
        cache.set(f"state_{chat_id}", {"step": "ADD_STUDENT_NAME"}, timeout=600)
        send_bale_message(chat_id, "👤 نام:")
    
    elif data.startswith("student_detail_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            msg = get_student_full_details(s)
            send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
    
    elif data.startswith("student_block_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_blocked = True
            s.save()
            # نمایش جزئیات به‌روز شده
            msg = get_student_full_details(s)
            send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
    
    elif data.startswith("student_unblock_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_blocked = False
            s.save()
            msg = get_student_full_details(s)
            send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
    
    elif data.startswith("student_deactivate_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_active = False
            s.save()
            msg = get_student_full_details(s)
            send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
    
    elif data.startswith("student_activate_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.is_active = True
            s.save()
            msg = get_student_full_details(s)
            send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
    
    elif data.startswith("student_del_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            s.delete()
        send_bale_message(chat_id, "🗑️ هنرجو حذف شد", reply_markup=build_manager_menu())
    
    elif data.startswith("student_edit_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_STUDENT_NAME", "student_id": sid}, timeout=600)
        send_bale_message(chat_id, "✏️ نام جدید:")
    
    elif data.startswith("student_parent_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_PARENT_NAME", "student_id": sid}, timeout=600)
        send_bale_message(chat_id, "👨‍👩‍👦 نام والدین:")
    
    elif data.startswith("student_sessions_"):
        sid = int(data.split("_")[-1])
        s = Student.objects.filter(id=sid).first()
        if s:
            sessions = s.sessions.filter(status__in=['confirmed', 'pending']).order_by('session_date')[:20]
            if not sessions.exists():
                send_bale_message(chat_id, "📅 جلسه‌ای نیست.")
            else:
                msg = f"📅 **جلسات {s.get_full_name()}:**\n\n"
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
                msg = f"🏠 **غیبت‌های {s.get_full_name()}:**\n\n"
                for a in absences:
                    status_map = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
                    msg += f"{status_map.get(a.status, '?')} {a.reason[:40]}\n"
                    if a.session:
                        local_dt = get_local_time(a.session.session_date)
                        msg += f"   📅 {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                    msg += f"{'─'*20}\n"
                
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
                send_bale_message(chat_id, "🔄 جابجایی نیست.")
            else:
                msg = f"🔄 **جابجایی‌های {s.get_full_name()}:**\n\n"
                for sw in swaps:
                    status_map = {'pending': '⏳', 'accepted': '✅', 'rejected': '❌', 'expired': '⏰'}
                    is_requester = sw.requesting_student == s
                    other = sw.target_student if is_requester else sw.requesting_student
                    
                    msg += f"{status_map.get(sw.status, '?')} "
                    msg += "درخواست" if is_requester else "دریافت"
                    if other:
                        msg += f" با {other.get_full_name()}"
                    msg += f"\n📅 {jdatetime.datetime.fromgregorian(datetime=sw.created_at).strftime('%Y/%m/%d')}\n"
                    msg += f"{'─'*20}\n"
                
                keyboard = {"inline_keyboard": [[{"text": "❌ بازگشت", "callback_data": f"student_detail_{s.id}"}]]}
                send_bale_message(chat_id, msg, reply_markup=keyboard)


def handle_student_text(chat_id, text, text_en, state):
    """مدیریت text های هنرجو در پنل مدیر"""
    step = state.get('step', '') if state else ''
    
    if step == 'SEARCH_STUDENT':
        students = Student.objects.filter(
            Q(first_name__icontains=text) | 
            Q(last_name__icontains=text) | 
            Q(phone_number__icontains=text_en)
        )[:10]
        
        cache.delete(f"state_{chat_id}")
        
        if not students.exists():
            send_bale_message(chat_id, "❌ هنرجویی یافت نشد", reply_markup=build_manager_menu())
        else:
            keyboard = []
            for s in students:
                keyboard.append([
                    {"text": f"👤 {s.get_full_name()}", "callback_data": f"student_detail_{s.id}"}
                ])
            keyboard.append([{"text": "❌ بازگشت", "callback_data": "manage_students"}])
            
            send_bale_message(chat_id, "🔍 **نتایج جستجو:**", reply_markup={"inline_keyboard": keyboard})
    
    elif step == 'ADD_STUDENT_NAME':
        state['first_name'] = text
        state['step'] = 'ADD_STUDENT_LAST'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "نام خانوادگی:")
    
    elif step == 'ADD_STUDENT_LAST':
        state['last_name'] = text
        state['step'] = 'ADD_STUDENT_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱 شماره موبایل:")
    
    elif step == 'ADD_STUDENT_PHONE':
        if re.match(r'^09\d{9}$', text_en):
            state['phone'] = text_en
            state['step'] = 'ADD_STUDENT_PARENT_NAME'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "👨‍👩‍👦 نام والدین (یا -):")
        else:
            send_bale_message(chat_id, "❌ شماره نامعتبر. مثال: 09123456789")
    
    elif step == 'ADD_STUDENT_PARENT_NAME':
        state['parent_name'] = text if text != '-' else None
        state['step'] = 'ADD_STUDENT_PARENT_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱 تلفن والدین (یا -):")
    
    elif step == 'ADD_STUDENT_PARENT_PHONE':
        parent_phone = text if text != '-' else None
        
        student = Student.objects.create(
            first_name=state['first_name'],
            last_name=state['last_name'],
            phone_number=state['phone'],
            parent_name=state.get('parent_name'),
            parent_phone=parent_phone
        )
        
        cache.delete(f"state_{chat_id}")
        
        msg = f"✅ هنرجو ثبت شد:\n\n"
        msg += f"👤 {student.get_full_name()}\n"
        msg += f"📱 {student.phone_number}"
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "📋 جزئیات", "callback_data": f"student_detail_{student.id}"}],
                [{"text": "❌ بازگشت", "callback_data": "manage_students"}]
            ]
        }
        send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif step == 'EDIT_STUDENT_NAME':
        s = Student.objects.filter(id=state['student_id']).first()
        if s:
            parts = text.split(' ')
            s.first_name = parts[0]
            s.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
            s.save()
            state['step'] = 'EDIT_STUDENT_PHONE'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📱 شماره جدید:")
    
    elif step == 'EDIT_STUDENT_PHONE':
        s = Student.objects.filter(id=state['student_id']).first()
        if s:
            if re.match(r'^09\d{9}$', text_en):
                s.phone_number = text_en
                s.save()
                cache.delete(f"state_{chat_id}")
                msg = get_student_full_details(s)
                send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
            else:
                send_bale_message(chat_id, "❌ شماره نامعتبر")
    
    elif step == 'EDIT_PARENT_NAME':
        s = Student.objects.filter(id=state['student_id']).first()
        if s:
            s.parent_name = text if text != '-' else None
            s.save()
            state['step'] = 'EDIT_PARENT_PHONE'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📱 تلفن والدین:")
    
    elif step == 'EDIT_PARENT_PHONE':
        s = Student.objects.filter(id=state['student_id']).first()
        if s:
            s.parent_phone = text if text != '-' else None
            s.save()
            cache.delete(f"state_{chat_id}")
            msg = get_student_full_details(s)
            send_bale_message(chat_id, msg, reply_markup=build_student_detail_keyboard(s))
    
    elif step == 'WARNING_SELECT':
        students = Student.objects.filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text)
        )[:5]
        
        if students.exists():
            state['students_list'] = list(students.values_list('id', flat=True))
            state['step'] = 'WARNING_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            
            msg = "🔍 **نتایج:**\n\n"
            for i, s in enumerate(students, 1):
                msg += f"{i}. {s.get_full_name()}\n"
            
            send_bale_message(chat_id, msg + "\nشماره هنرجو:")
        else:
            send_bale_message(chat_id, "❌ هنرجویی یافت نشد")
    
    elif step == 'WARNING_NUM':
        try:
            idx = int(text_en) - 1
            if 0 <= idx < len(state['students_list']):
                state['student_id'] = state['students_list'][idx]
                state['step'] = 'WARNING_INTERVAL'
                cache.set(f"state_{chat_id}", state, timeout=600)
                send_bale_message(chat_id, "⏰ فاصله هشدار (ساعت):")
            else:
                send_bale_message(chat_id, "❌ شماره نامعتبر")
        except:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'WARNING_INTERVAL':
        if text_en.isdigit():
            s = Student.objects.filter(id=state['student_id']).first()
            if s:
                s.warning_interval_hours = int(text_en)
                s.save()
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, "✅ تنظیم شد", reply_markup=build_manager_menu())
        else:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'CREDIT_SELECT':
        students = Student.objects.filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text)
        )[:5]
        
        if students.exists():
            state['students_list'] = list(students.values_list('id', flat=True))
            state['step'] = 'CREDIT_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            
            msg = "🔍 **نتایج:**\n\n"
            for i, s in enumerate(students, 1):
                msg += f"{i}. {s.get_full_name()}\n"
            
            send_bale_message(chat_id, msg + "\nشماره هنرجو:")
        else:
            send_bale_message(chat_id, "❌ هنرجویی یافت نشد")
    
    elif step == 'CREDIT_NUM':
        try:
            idx = int(text_en) - 1
            if 0 <= idx < len(state['students_list']):
                state['student_id'] = state['students_list'][idx]
                state['step'] = 'CREDIT_AMOUNT'
                cache.set(f"state_{chat_id}", state, timeout=600)
                send_bale_message(chat_id, "🚫 رد لاین (تومان):")
            else:
                send_bale_message(chat_id, "❌ شماره نامعتبر")
        except:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'CREDIT_AMOUNT':
        try:
            amount = int(text_en)
            s = Student.objects.filter(id=state['student_id']).first()
            if s:
                s.credit_limit = amount
                s.save()
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, "✅ تنظیم شد", reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌ فقط عدد")