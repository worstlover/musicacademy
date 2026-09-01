import jdatetime
from datetime import datetime, timedelta, time

from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q

from core.models import Teacher, Student, ClassSession, Course, StudentCourse, TeacherRate
from ...utils import send_bale_message, get_local_time, get_teacher_rate
from ...keyboards import build_manager_menu


WEEK_DAYS_FA = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنج‌شنبه', 'جمعه']


def get_week_dates(week_offset=0):
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


def build_week_keyboard(week_offset=0):
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
    
    keyboard.append([
        {"text": "⬅️", "callback_data": f"weeknav_{week_offset - 1}"},
        {"text": "📅", "callback_data": "weeknav_0"},
        {"text": "➡️", "callback_data": f"weeknav_{week_offset + 1}"}
    ])
    keyboard.append([{"text": "❌", "callback_data": "back_to_manager"}])
    return {"inline_keyboard": keyboard}


def get_teacher_schedule(teacher, date):
    return ClassSession.objects.filter(
        teacher=teacher,
        session_date__date=date,
        status__in=['pending', 'confirmed']
    ).order_by('session_date')


def build_day_schedule_keyboard(teacher, date):
    sessions = get_teacher_schedule(teacher, date)
    keyboard = []
    for s in sessions:
        local_dt = get_local_time(s.session_date)
        t = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')
        label = f"{t} - {s.student.get_full_name()}"
        if s.course:
            label += f" ({s.course.name})"
        keyboard.append([{"text": label, "callback_data": f"session_detail_{s.id}"}])
    keyboard.append([{"text": "➕ افزودن جلسه", "callback_data": f"add_session_{teacher.id}_{date.strftime('%Y-%m-%d')}"}])
    keyboard.append([{"text": "📋 کپی برنامه", "callback_data": f"copy_sched_{teacher.id}_{date.strftime('%Y-%m-%d')}"}])
    keyboard.append([{"text": "❌ بازگشت", "callback_data": f"teacher_sched_{teacher.id}"}])
    return {"inline_keyboard": keyboard}


def check_time_conflict(teacher, date, start_time, duration_minutes, exclude_id=None):
    sessions = ClassSession.objects.filter(
        teacher=teacher, session_date__date=date, status__in=['pending', 'confirmed']
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
    source_sessions = get_teacher_schedule(teacher, source_date)
    if not source_sessions.exists():
        return 0, ["برنامه‌ای نیست"]
    
    copied = 0
    errors = []
    for week in target_weeks:
        target_date = source_date + timedelta(weeks=week)
        for s in source_sessions:
            local_dt = get_local_time(s.session_date)
            start_time = local_dt.time()
            conflict, _ = check_time_conflict(teacher, target_date, start_time.strftime('%H:%M'), s.duration_minutes)
            if conflict:
                errors.append(f"تداخل: {s.student.get_full_name()}")
            else:
                new_dt = timezone.make_aware(datetime.combine(target_date, start_time))
                ClassSession.objects.create(
                    student=s.student, 
                    teacher=teacher,
                    course=s.course,
                    duration_minutes=s.duration_minutes,
                    session_date=new_dt, 
                    fee=s.fee, 
                    status='pending'
                )
                copied += 1
    return copied, errors


def handle_schedule_callback(chat_id, data, state):
    """مدیریت callback های برنامه‌ریزی"""
    
    if data == "weekly_planning":
        cache.set(f"state_{chat_id}", {"step": "PLAN_SELECT_TEACHER"}, timeout=600)
        send_bale_message(chat_id, "👨‍🏫 نام استاد:")
    
    elif data.startswith("weeknav_"):
        week_offset = int(data.split("_")[1])
        current_state = cache.get(f"state_{chat_id}") or state or {}
        
        if current_state.get('teacher_id'):
            teacher = Teacher.objects.filter(id=current_state['teacher_id']).first()
            if teacher:
                current_state['week_offset'] = week_offset
                cache.set(f"state_{chat_id}", current_state, timeout=600)
                dates = get_week_dates(week_offset)
                msg = f"👨‍🏫 {teacher.get_full_name()}\n\n📅 انتخاب روز:\n\n"
                for d in dates:
                    msg += f"• {d['day_name']} - {d['jalali']}\n"
                send_bale_message(chat_id, msg, reply_markup=build_week_keyboard(week_offset))
    
    elif data.startswith("planday_"):
        parts = data.split("_")
        day_index = int(parts[1])
        week_offset = int(parts[2])
        
        current_state = cache.get(f"state_{chat_id}") or state or {}
        
        if current_state.get('teacher_id'):
            teacher = Teacher.objects.filter(id=current_state['teacher_id']).first()
            if teacher:
                dates = get_week_dates(week_offset)
                selected_date = dates[day_index]['date']
                current_state['selected_date'] = selected_date.strftime('%Y-%m-%d')
                current_state['week_offset'] = week_offset
                cache.set(f"state_{chat_id}", current_state, timeout=600)
                
                sessions = get_teacher_schedule(teacher, selected_date)
                jd = jdatetime.date.fromgregorian(date=selected_date)
                msg = f"👨‍🏫 {teacher.get_full_name()}\n"
                msg += f"📅 {dates[day_index]['day_name']} - {jd.strftime('%Y/%m/%d')}\n\n"
                
                if sessions.exists():
                    msg += "📋 **برنامه:**\n"
                    for s in sessions:
                        local_dt = get_local_time(s.session_date)
                        t = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')
                        status_emoji = {'pending': '⏳', 'confirmed': '✅'}.get(s.status, '?')
                        msg += f"{status_emoji} {t} - {s.student.get_full_name()}"
                        if s.course:
                            msg += f" ({s.course.name})"
                        msg += f"\n   ⏱️ {s.duration_minutes} دقیقه | 💰 {s.fee:,} تومان\n"
                        msg += f"{'─'*20}\n"
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
    
    elif data.startswith("copy_sched_"):
        parts = data.split("_")
        tid = int(parts[2])
        date_str = parts[3]
        cache.set(f"state_{chat_id}", {"step": "COPY_WEEKS", "teacher_id": tid, "source_date": date_str}, timeout=600)
        send_bale_message(chat_id, "📋 به چند هفته کپی شود؟\n(مثال: 1 یا 1,2,3 یا 1-4)")
    
    elif data.startswith("add_session_"):
        parts = data.split("_")
        tid = int(parts[2])
        date_str = parts[3]
        cache.set(f"state_{chat_id}", {"step": "ADD_SESSION_STUDENT", "teacher_id": tid, "session_date": date_str}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو:")
    
    elif data.startswith("session_detail_"):
        sid = int(data.split("_")[-1])
        session = ClassSession.objects.filter(id=sid).first()
        if session:
            local_dt = get_local_time(session.session_date)
            msg = f"📋 **جزئیات جلسه**\n\n"
            msg += f"👤 هنرجو: {session.student.get_full_name()}\n"
            msg += f"👨‍🏫 استاد: {session.teacher.get_full_name()}\n"
            
            if session.course:
                msg += f"🎵 کلاس: {session.course.name}\n"
                if session.course.rate_template:
                    msg += f"📋 قالب: {session.course.rate_template.name}\n"
            
            msg += f"📅 تاریخ: {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
            msg += f"⏱️ مدت: {session.duration_minutes} دقیقه\n"
            msg += f"💰 هزینه: {session.fee:,} تومان\n"
            msg += f"📊 وضعیت: {'✅ تایید شده' if session.status == 'confirmed' else '⏳ در انتظار'}\n"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✏️ ویرایش ساعت", "callback_data": f"edit_time_{sid}"}],
                    [{"text": "⏱️ ویرایش مدت", "callback_data": f"edit_dur_{sid}"}],
                    [{"text": "🗑️ حذف جلسه", "callback_data": f"del_sess_{sid}"}],
                    [{"text": "❌ بازگشت", "callback_data": f"teacher_sched_{session.teacher.id}"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("edit_time_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_SESSION_TIME", "session_id": sid}, timeout=600)
        send_bale_message(chat_id, "⏰ ساعت جدید (مثال: 14:00):")
    
    elif data.startswith("edit_dur_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "EDIT_SESSION_DURATION", "session_id": sid}, timeout=600)
        send_bale_message(chat_id, "⏱️ مدت جدید (دقیقه):")
    
    elif data.startswith("del_sess_"):
        sid = int(data.split("_")[-1])
        session = ClassSession.objects.filter(id=sid).first()
        if session:
            teacher_id = session.teacher.id
            session.delete()
            send_bale_message(
                chat_id, 
                "🗑️ جلسه حذف شد",
                reply_markup={"inline_keyboard": [[{"text": "❌ بازگشت", "callback_data": f"teacher_sched_{teacher_id}"}]]}
            )


def handle_schedule_text(chat_id, text, text_en, state):
    """مدیریت text های برنامه‌ریزی"""
    step = state.get('step', '') if state else ''
    
    if step == 'PLAN_SELECT_TEACHER':
        teachers = Teacher.objects.filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text)
        )[:5]
        
        if teachers.exists():
            state['teachers_list'] = list(teachers.values_list('id', flat=True))
            state['step'] = 'PLAN_SELECT_TEACHER_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            
            msg = "🔍 **نتایج:**\n\n"
            for i, t in enumerate(teachers, 1):
                msg += f"{i}. {t.get_full_name()}\n"
            
            send_bale_message(chat_id, msg + "\nشماره استاد:")
        else:
            send_bale_message(chat_id, "❌ استادی یافت نشد")
    
    elif step == 'PLAN_SELECT_TEACHER_NUM':
        try:
            idx = int(text_en) - 1
            if 0 <= idx < len(state['teachers_list']):
                state['teacher_id'] = state['teachers_list'][idx]
                state['step'] = 'PLAN_DAY_SELECT'
                state['week_offset'] = 0
                cache.set(f"state_{chat_id}", state, timeout=600)
                
                dates = get_week_dates(0)
                msg = "📅 **انتخاب روز:**\n\n"
                for d in dates:
                    msg += f"• {d['day_name']} - {d['jalali']}\n"
                
                send_bale_message(chat_id, msg, reply_markup=build_week_keyboard(0))
            else:
                send_bale_message(chat_id, "❌ شماره نامعتبر")
        except:
            send_bale_message(chat_id, "❌ فقط عدد وارد کنید")
    
    elif step == 'COPY_WEEKS':
        teacher = Teacher.objects.get(id=state['teacher_id'])
        source_date = datetime.strptime(state['source_date'], '%Y-%m-%d').date()
        
        weeks = []
        t = text_en.strip()
        if '-' in t:
            parts = t.split('-')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                start, end = int(parts[0]), int(parts[1])
                weeks = list(range(start, end + 1))
        elif ',' in t:
            weeks = [int(w.strip()) for w in t.split(',') if w.strip().isdigit()]
        elif t.isdigit():
            weeks = [int(t)]
        
        if weeks:
            copied, errors = copy_schedule(teacher, source_date, weeks)
            msg = f"✅ {copied} جلسه کپی شد"
            if errors:
                msg += f"\n⚠️ {len(errors)} تداخل"
        else:
            msg = "❌ فرمت نامعتبر"
        
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
    
    elif step == 'ADD_SESSION_STUDENT':
        students = Student.objects.filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text)
        )[:5]
        
        if students.exists():
            state['students_list'] = list(students.values_list('id', flat=True))
            state['step'] = 'ADD_SESSION_STUDENT_NUM'
            cache.set(f"state_{chat_id}", state, timeout=600)
            
            msg = "🔍 **نتایج:**\n\n"
            for i, s in enumerate(students, 1):
                msg += f"{i}. {s.get_full_name()}\n"
            
            send_bale_message(chat_id, msg + "\nشماره هنرجو:")
        else:
            send_bale_message(chat_id, "❌ هنرجویی یافت نشد")
    
    elif step == 'ADD_SESSION_STUDENT_NUM':
        try:
            idx = int(text_en) - 1
            if 0 <= idx < len(state['students_list']):
                state['student_id'] = state['students_list'][idx]
                student = Student.objects.get(id=state['student_id'])
                
                # نمایش کلاس‌های ثبت‌نام شده هنرجو
                enrollments = student.enrollments.filter(is_active=True)
                if enrollments.exists():
                    state['enrollments_list'] = list(enrollments.values_list('id', flat=True))
                    state['step'] = 'ADD_SESSION_COURSE'
                    cache.set(f"state_{chat_id}", state, timeout=600)
                    
                    msg = f"👤 {student.get_full_name()}\n\n"
                    msg += "🎵 **انتخاب کلاس:**\n\n"
                    for i, e in enumerate(enrollments, 1):
                        course = e.course
                        msg += f"{i}. {course.name}\n"
                        msg += f"   👨‍🏫 {course.teacher.get_full_name()}\n"
                        if course.rate_template:
                            msg += f"   📋 {course.rate_template.name}\n"
                        msg += f"   💰 {course.calculate_fee():,} تومان\n"
                        msg += f"   ⏱️ {course.duration_minutes} دقیقه\n\n"
                    
                    send_bale_message(chat_id, msg + "شماره کلاس:")
                else:
                    send_bale_message(
                        chat_id, 
                        "⚠️ هنرجو در کلاسی ثبت‌نام نکرده.\nابتدا در بخش مدیریت کلاس‌ها ثبت‌نام کنید.",
                        reply_markup=build_manager_menu()
                    )
                    cache.delete(f"state_{chat_id}")
            else:
                send_bale_message(chat_id, "❌ شماره نامعتبر")
        except Exception as e:
            send_bale_message(chat_id, f"❌ خطا: {e}")
    
    elif step == 'ADD_SESSION_COURSE':
        try:
            idx = int(text_en) - 1
            if 0 <= idx < len(state['enrollments_list']):
                enrollment_id = state['enrollments_list'][idx]
                enrollment = StudentCourse.objects.get(id=enrollment_id)
                course = enrollment.course
                
                state['course_id'] = course.id
                state['step'] = 'ADD_SESSION_TIME'
                cache.set(f"state_{chat_id}", state, timeout=600)
                send_bale_message(chat_id, "⏰ ساعت جلسه (مثال: 14:00):")
            else:
                send_bale_message(chat_id, "❌ شماره نامعتبر")
        except:
            send_bale_message(chat_id, "❌ فقط عدد وارد کنید")
    
    elif step == 'ADD_SESSION_TIME':
        try:
            if ':' not in text:
                send_bale_message(chat_id, "❌ فرمت: 14:00")
                return
            
            parts = text.split(':')
            if len(parts) != 2:
                send_bale_message(chat_id, "❌ فرمت: 14:00")
                return
            
            h = int(parts[0].strip())
            m = int(parts[1].strip())
            
            if h < 0 or h > 23 or m < 0 or m > 59:
                send_bale_message(chat_id, "❌ ساعت نامعتبر")
                return
            
            state['start_time'] = f"{h:02d}:{m:02d}"
            state['step'] = 'ADD_SESSION_DURATION'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "⏱️ مدت جلسه (دقیقه):")
        except:
            send_bale_message(chat_id, "❌ فرمت: 14:00")
    
    elif step == 'ADD_SESSION_DURATION':
        if text_en.isdigit():
            duration = int(text_en)
            teacher = Teacher.objects.get(id=state['teacher_id'])
            student = Student.objects.get(id=state['student_id'])
            course = Course.objects.get(id=state['course_id'])
            date_obj = datetime.strptime(state['session_date'], '%Y-%m-%d').date()
            
            conflict, conflict_session = check_time_conflict(teacher, date_obj, state['start_time'], duration)
            
            if conflict:
                if conflict_session:
                    local_dt = get_local_time(conflict_session.session_date)
                    conflict_time = jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%H:%M')
                    send_bale_message(
                        chat_id, 
                        f"❌ تداخل زمانی!\n\n"
                        f"⏰ {conflict_time} - {conflict_session.student.get_full_name()}\n"
                        f"⏱️ {conflict_session.duration_minutes} دقیقه"
                    )
                else:
                    send_bale_message(chat_id, "❌ تداخل زمانی!")
            else:
                # محاسبه هزینه بر اساس course
                fee = course.calculate_fee(duration)
                
                dt = timezone.make_aware(datetime.combine(date_obj, time.fromisoformat(state['start_time'])))
                session = ClassSession.objects.create(
                    student=student, 
                    teacher=teacher,
                    course=course,
                    duration_minutes=duration, 
                    session_date=dt,
                    fee=fee, 
                    status='pending'
                )
                
                msg = f"✅ **جلسه ثبت شد**\n\n"
                msg += f"👤 {student.get_full_name()}\n"
                msg += f"👨‍🏫 {teacher.get_full_name()}\n"
                msg += f"🎵 {course.name}\n"
                if course.rate_template:
                    msg += f"📋 {course.rate_template.name}\n"
                msg += f"📅 {jdatetime.date.fromgregorian(date=date_obj).strftime('%Y/%m/%d')}\n"
                msg += f"⏰ {state['start_time']}\n"
                msg += f"⏱️ {duration} دقیقه\n"
                msg += f"💰 {fee:,} تومان"
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "❌ بازگشت", "callback_data": f"teacher_sched_{teacher.id}"}]
                    ]
                }
                send_bale_message(chat_id, msg, reply_markup=keyboard)
            
            cache.delete(f"state_{chat_id}")
        else:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'EDIT_SESSION_TIME':
        try:
            if ':' not in text:
                send_bale_message(chat_id, "❌ فرمت: 14:00")
                return
            
            parts = text.split(':')
            if len(parts) != 2:
                send_bale_message(chat_id, "❌ فرمت: 14:00")
                return
            
            h = int(parts[0].strip())
            m = int(parts[1].strip())
            
            if h < 0 or h > 23 or m < 0 or m > 59:
                send_bale_message(chat_id, "❌ ساعت نامعتبر")
                return
            
            session = ClassSession.objects.get(id=state['session_id'])
            cur = get_local_time(session.session_date)
            
            # چک تداخل
            conflict, _ = check_time_conflict(
                session.teacher, 
                cur.date(), 
                f"{h:02d}:{m:02d}", 
                session.duration_minutes,
                exclude_id=session.id
            )
            
            if conflict:
                send_bale_message(chat_id, "❌ تداخل زمانی!")
            else:
                session.session_date = timezone.make_aware(datetime.combine(cur.date(), time(h, m)))
                session.save()
                send_bale_message(chat_id, "✅ ساعت ویرایش شد")
            
            cache.delete(f"state_{chat_id}")
        except:
            send_bale_message(chat_id, "❌ فرمت: 14:00")
    
    elif step == 'EDIT_SESSION_DURATION':
        if text_en.isdigit():
            duration = int(text_en)
            session = ClassSession.objects.get(id=state['session_id'])
            
            # چک تداخل با مدت جدید
            cur = get_local_time(session.session_date)
            conflict, _ = check_time_conflict(
                session.teacher,
                cur.date(),
                cur.time().strftime('%H:%M'),
                duration,
                exclude_id=session.id
            )
            
            if conflict:
                send_bale_message(chat_id, "❌ تداخل زمانی!")
            else:
                session.duration_minutes = duration
                
                # محاسبه هزینه بر اساس course
                if session.course:
                    session.fee = session.course.calculate_fee(duration)
                else:
                    session.fee = get_teacher_rate(session.teacher) * duration // 60
                
                session.save()
                send_bale_message(chat_id, "✅ مدت ویرایش شد")
            
            cache.delete(f"state_{chat_id}")
        else:
            send_bale_message(chat_id, "❌ فقط عدد")