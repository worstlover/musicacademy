import jdatetime
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from core.models import Course, Teacher, Student, StudentCourse, RateTemplate, TeacherRate
from ...utils import send_bale_message, notify_student
from ...keyboards import build_manager_menu


def get_course_fee_display(course):
    """دریافت نمایش هزینه کلاس با اولویت TeacherRate"""
    if course.rate_template:
        teacher_rate = TeacherRate.objects.filter(
            teacher=course.teacher,
            rate_template=course.rate_template
        ).first()
        
        if teacher_rate:
            fee = teacher_rate.calculate_fee(course.duration_minutes)
            return f"{fee:,} تومان (تعرفه استاد: {teacher_rate.hourly_rate:,}/ساعت)"
        else:
            fee = (course.base_fee * course.duration_minutes) // 60 if course.base_fee > 0 else 0
            return f"{fee:,} تومان (پایه) ⚠️ استاد تعرفه ندارد"
    else:
        fee = (course.base_fee * course.duration_minutes) // 60 if course.base_fee > 0 else 0
        return f"{fee:,} تومان (پایه)"


def show_course_details(chat_id, course):
    """نمایش جزئیات کامل کلاس"""
    msg = f"🎵 **{course.name}**\n\n"
    msg += f"👨‍🏫 استاد: {course.teacher.get_full_name()}\n"
    
    if course.rate_template:
        msg += f"📋 قالب: {course.rate_template.name}\n"
        
        # نمایش تعرفه استاد برای این قالب
        teacher_rate = TeacherRate.objects.filter(
            teacher=course.teacher,
            rate_template=course.rate_template
        ).first()
        
        if teacher_rate:
            msg += f"💰 تعرفه استاد: {teacher_rate.hourly_rate:,} تومان/ساعت\n"
            msg += f"💵 هزینه جلسه: {teacher_rate.calculate_fee(course.duration_minutes):,} تومان\n"
        else:
            msg += f"⚠️ استاد تعرفه‌ای برای این قالب ندارد!\n"
            if course.base_fee > 0:
                msg += f"💰 هزینه پایه: {(course.base_fee * course.duration_minutes) // 60:,} تومان\n"
    else:
        if course.base_fee > 0:
            msg += f"💰 هزینه پایه: {(course.base_fee * course.duration_minutes) // 60:,} تومان\n"
    
    msg += f"⏱️ مدت: {course.duration_minutes} دقیقه\n"
    msg += f"👥 هنرجو: {course.enrollments.filter(is_active=True).count()} نفر\n"
    msg += f"🔴 وضعیت: {'فعال' if course.is_active else 'غیرفعال'}\n"
    
    return msg


def handle_course_callback(chat_id, data, state):
    """مدیریت callback های کلاس"""
    
    if data == "manage_courses":
        courses = Course.objects.filter(is_active=True).order_by('name')
        if not courses.exists():
            keyboard = {
                "inline_keyboard": [
                    [{"text": "➕ ایجاد کلاس", "callback_data": "add_course"}],
                    [{"text": "❌ بازگشت", "callback_data": "back_to_manager"}]
                ]
            }
            send_bale_message(chat_id, "🎵 کلاسی وجود ندارد.", reply_markup=keyboard)
        else:
            msg = "🎵 **کلاس‌ها:**\n\n"
            keyboard = []
            for c in courses:
                msg += f"• {c.name}\n"
                msg += f"  👨‍🏫 {c.teacher.get_full_name()}\n"
                if c.rate_template:
                    msg += f"  📋 {c.rate_template.name}\n"
                msg += f"  💰 {get_course_fee_display(c)}\n"
                msg += f"  ⏱️ {c.duration_minutes} دقیقه\n"
                msg += f"  👥 {c.enrollments.filter(is_active=True).count()} هنرجو\n"
                msg += f"{'─'*20}\n"
                
                keyboard.append([{"text": f"✏️ {c.name}", "callback_data": f"course_detail_{c.id}"}])
            
            keyboard.append([{"text": "➕ ایجاد کلاس", "callback_data": "add_course"}])
            keyboard.append([{"text": "❌ بازگشت", "callback_data": "back_to_manager"}])
            
            send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data == "add_course":
        # انتخاب استاد
        teachers = Teacher.objects.filter(is_active=True)
        if not teachers.exists():
            send_bale_message(chat_id, "❌ ابتدا استاد ثبت کنید.")
            return
        
        cache.set(f"state_{chat_id}", {"step": "ADD_COURSE_TEACHER"}, timeout=600)
        
        msg = "👨‍🏫 **انتخاب استاد:**\n\n"
        keyboard = []
        for t in teachers:
            # نمایش تعرفه‌های استاد
            rates = t.rates.select_related('rate_template').all()
            rate_info = ""
            if rates.exists():
                rate_info = "\n"
                for tr in rates:
                    rate_info += f"     📋 {tr.rate_template.name}: {tr.hourly_rate:,}\n"
            
            msg += f"• {t.get_full_name()}{rate_info}\n"
            keyboard.append([{"text": t.get_full_name(), "callback_data": f"addcourse_teacher_{t.id}"}])
        
        keyboard.append([{"text": "❌ بازگشت", "callback_data": "manage_courses"}])
        send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("addcourse_teacher_"):
        tid = int(data.split("_")[-1])
        teacher = Teacher.objects.filter(id=tid).first()
        if teacher:
            state = {"step": "ADD_COURSE_NAME", "teacher_id": tid}
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, f"👨‍🏫 {teacher.get_full_name()}\n\n📝 نام کلاس:")
    
    elif data.startswith("course_detail_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            msg = show_course_details(chat_id, course)
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "👥 هنرجویان", "callback_data": f"course_students_{course.id}"}],
                    [{"text": "➕ ثبت‌نام", "callback_data": f"course_enroll_{course.id}"}],
                    [{"text": "📨 ارسال پیام", "callback_data": f"course_message_{course.id}"}],
                    [{"text": "✏️ ویرایش", "callback_data": f"course_edit_menu_{course.id}"}],
                    [{"text": "🗑️ حذف", "callback_data": f"course_delete_{course.id}"}],
                    [{"text": "❌ بازگشت", "callback_data": "manage_courses"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("course_edit_menu_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            msg = f"✏️ **ویرایش {course.name}**\n\n"
            msg += "چه چیزی را ویرایش می‌کنید؟"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📝 نام کلاس", "callback_data": f"course_edit_name_{course.id}"}],
                    [{"text": "👨‍🏫 استاد", "callback_data": f"course_edit_teacher_{course.id}"}],
                    [{"text": "📋 قالب تعرفه", "callback_data": f"course_edit_rate_{course.id}"}],
                    [{"text": "⏱️ مدت جلسه", "callback_data": f"course_edit_duration_{course.id}"}],
                    [{"text": "💰 هزینه پایه", "callback_data": f"course_edit_fee_{course.id}"}],
                    [{"text": "❌ بازگشت", "callback_data": f"course_detail_{course.id}"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("course_edit_name_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            cache.set(f"state_{chat_id}", {"step": "EDIT_COURSE_NAME", "course_id": cid}, timeout=600)
            send_bale_message(chat_id, f"📝 نام جدید (فعلی: {course.name}):")
    
    elif data.startswith("course_edit_teacher_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            cache.set(f"state_{chat_id}", {"step": "EDIT_COURSE_TEACHER", "course_id": cid}, timeout=600)
            
            teachers = Teacher.objects.filter(is_active=True)
            msg = f"👨‍🏫 **انتخاب استاد جدید** (فعلی: {course.teacher.get_full_name()}):\n\n"
            keyboard = []
            for t in teachers:
                msg += f"• {t.get_full_name()}\n"
                keyboard.append([{"text": t.get_full_name(), "callback_data": f"editcourse_teacher_{t.id}"}])
            
            keyboard.append([{"text": "❌ بازگشت", "callback_data": f"course_detail_{cid}"}])
            send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("editcourse_teacher_"):
        tid = int(data.split("_")[-1])
        current_state = cache.get(f"state_{chat_id}") or {}
        course_id = current_state.get('course_id')
        
        if course_id:
            course = Course.objects.filter(id=course_id).first()
            teacher = Teacher.objects.filter(id=tid).first()
            if course and teacher:
                course.teacher = teacher
                course.save()
                
                cache.delete(f"state_{chat_id}")
                msg = show_course_details(chat_id, course)
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "❌ بازگشت", "callback_data": f"course_detail_{course.id}"}]
                    ]
                }
                send_bale_message(chat_id, "✅ استاد ویرایش شد.\n\n" + msg, reply_markup=keyboard)
    
    elif data.startswith("course_edit_rate_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            cache.set(f"state_{chat_id}", {"step": "EDIT_COURSE_RATE", "course_id": cid}, timeout=600)
            
            rate_templates = RateTemplate.objects.filter(is_active=True)
            msg = f"📋 **انتخاب قالب تعرفه**\n"
            msg += f"فعلی: {course.rate_template.name if course.rate_template else 'ندارد'}\n\n"
            
            keyboard = []
            for rt in rate_templates:
                # نمایش تعرفه استاد برای این قالب
                teacher_rate = TeacherRate.objects.filter(
                    teacher=course.teacher,
                    rate_template=rt
                ).first()
                
                if teacher_rate:
                    msg += f"• {rt.name}: {teacher_rate.hourly_rate:,} تومان/ساعت\n"
                else:
                    msg += f"• {rt.name}: ⚠️ تعرفه ندارد\n"
                
                keyboard.append([{"text": rt.name, "callback_data": f"editcourse_rate_{rt.id}"}])
            
            keyboard.append([{"text": "⏭️ بدون تعرفه", "callback_data": "editcourse_rate_none"}])
            keyboard.append([{"text": "❌ بازگشت", "callback_data": f"course_detail_{cid}"}])
            send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("course_edit_duration_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            cache.set(f"state_{chat_id}", {"step": "EDIT_COURSE_DURATION", "course_id": cid}, timeout=600)
            send_bale_message(chat_id, f"⏱️ مدت جدید (فعلی: {course.duration_minutes} دقیقه):")
    
    elif data.startswith("course_edit_fee_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            cache.set(f"state_{chat_id}", {"step": "EDIT_COURSE_FEE", "course_id": cid}, timeout=600)
            send_bale_message(chat_id, f"💰 هزینه پایه جدید (فعلی: {course.base_fee:,} تومان):")
    
    elif data.startswith("course_students_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            enrollments = course.enrollments.filter(is_active=True)
            if not enrollments.exists():
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "➕ ثبت‌نام هنرجو", "callback_data": f"course_enroll_{course.id}"}],
                        [{"text": "❌ بازگشت", "callback_data": f"course_detail_{course.id}"}]
                    ]
                }
                send_bale_message(chat_id, "👥 هنرجویی ثبت‌نام نکرده.", reply_markup=keyboard)
            else:
                msg = f"👥 **هنرجویان {course.name}:**\n\n"
                keyboard = []
                for e in enrollments:
                    s = e.student
                    msg += f"• {s.get_full_name()}\n"
                    msg += f"  📱 {s.phone_number}\n"
                    msg += f"  💰 موجودی: {s.wallet_balance:,}\n"
                    msg += f"{'─'*20}\n"
                    
                    keyboard.append([
                        {"text": f"🗑️ حذف {s.get_full_name()}", "callback_data": f"course_remove_student_{e.id}"}
                    ])
                
                keyboard.append([{"text": "➕ ثبت‌نام", "callback_data": f"course_enroll_{course.id}"}])
                keyboard.append([{"text": "❌ بازگشت", "callback_data": f"course_detail_{course.id}"}])
                send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("course_remove_student_"):
        eid = int(data.split("_")[-1])
        enrollment = StudentCourse.objects.filter(id=eid).first()
        if enrollment:
            course_id = enrollment.course.id
            student_name = enrollment.student.get_full_name()
            enrollment.is_active = False
            enrollment.save()
            
            send_bale_message(
                chat_id, 
                f"🗑️ {student_name} از کلاس حذف شد.",
                reply_markup={"inline_keyboard": [[{"text": "❌ بازگشت", "callback_data": f"course_students_{course_id}"}]]}
            )
    
    elif data.startswith("course_enroll_"):
        cid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "ENROLL_STUDENT_SEARCH", "course_id": cid}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو برای ثبت‌نام:")
    
    elif data.startswith("course_message_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            cache.set(f"state_{chat_id}", {"step": "COURSE_MESSAGE_TEXT", "course_id": cid}, timeout=600)
            send_bale_message(chat_id, f"📨 **ارسال پیام به هنرجویان {course.name}**\n\nمتن پیام را وارد کنید:")
    
    elif data.startswith("course_delete_"):
        cid = int(data.split("_")[-1])
        course = Course.objects.filter(id=cid).first()
        if course:
            course.is_active = False
            course.save()
            send_bale_message(chat_id, "🗑️ کلاس غیرفعال شد.", reply_markup=build_manager_menu())


def handle_course_special_callback(chat_id, data, state):
    """مدیریت callback های خاص کلاس - انتخاب تعرفه و ثبت‌نام"""
    
    # ============ انتخاب تعرفه برای کلاس جدید ============
    if data.startswith("addcourse_rate_"):
        rate_id = data.split("_")[-1]
        
        current_state = cache.get(f"state_{chat_id}") or state or {}
        
        if rate_id == "none":
            current_state['rate_template_id'] = None
        else:
            current_state['rate_template_id'] = int(rate_id)
        
        current_state['step'] = 'ADD_COURSE_DURATION'
        cache.set(f"state_{chat_id}", current_state, timeout=600)
        send_bale_message(chat_id, "⏱️ مدت هر جلسه (دقیقه):")
    
    # ============ انتخاب تعرفه برای ویرایش کلاس ============
    elif data.startswith("editcourse_rate_"):
        rate_id = data.split("_")[-1]
        
        current_state = cache.get(f"state_{chat_id}") or {}
        course_id = current_state.get('course_id')
        
        if course_id:
            course = Course.objects.filter(id=course_id).first()
            if course:
                if rate_id == "none":
                    course.rate_template = None
                else:
                    rate_template = RateTemplate.objects.filter(id=int(rate_id)).first()
                    if rate_template:
                        course.rate_template = rate_template
                
                course.save()
                cache.delete(f"state_{chat_id}")
                
                msg = show_course_details(chat_id, course)
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "❌ بازگشت", "callback_data": f"course_detail_{course.id}"}]
                    ]
                }
                send_bale_message(chat_id, "✅ قالب تعرفه ویرایش شد.\n\n" + msg, reply_markup=keyboard)
    
    # ============ ثبت‌نام هنرجو ============
    elif data.startswith("enroll_student_"):
        sid = int(data.split("_")[-1])
        current_state = cache.get(f"state_{chat_id}") or {}
        course_id = current_state.get('course_id')
        
        if course_id:
            course = Course.objects.filter(id=course_id).first()
            student = Student.objects.filter(id=sid).first()
            
            if course and student:
                enrollment, created = StudentCourse.objects.get_or_create(
                    student=student,
                    course=course,
                    defaults={'is_active': True}
                )
                
                if not created and not enrollment.is_active:
                    enrollment.is_active = True
                    enrollment.save()
                
                cache.delete(f"state_{chat_id}")
                
                msg = f"✅ {student.get_full_name()} در {course.name} ثبت‌نام شد."
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "👥 هنرجویان", "callback_data": f"course_students_{course.id}"}],
                        [{"text": "❌ بازگشت", "callback_data": f"course_detail_{course.id}"}]
                    ]
                }
                send_bale_message(chat_id, msg, reply_markup=keyboard)


def handle_course_text(chat_id, text, text_en, state):
    """مدیریت text های کلاس"""
    step = state.get('step', '') if state else ''
    
    if step == 'ADD_COURSE_NAME':
        state['course_name'] = text
        state['step'] = 'ADD_COURSE_RATE_TEMPLATE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        
        # انتخاب قالب تعرفه با نمایش تعرفه استاد
        teacher_id = state.get('teacher_id')
        teacher = Teacher.objects.filter(id=teacher_id).first()
        
        rate_templates = RateTemplate.objects.filter(is_active=True)
        msg = "📋 **انتخاب قالب تعرفه:**\n\n"
        
        if teacher:
            msg += f"👨‍🏫 {teacher.get_full_name()}\n\n"
        
        keyboard = []
        for rt in rate_templates:
            # نمایش تعرفه استاد برای این قالب
            teacher_rate = None
            if teacher:
                teacher_rate = TeacherRate.objects.filter(
                    teacher=teacher,
                    rate_template=rt
                ).first()
            
            if teacher_rate:
                msg += f"• {rt.name}: {teacher_rate.hourly_rate:,} تومان/ساعت\n"
            else:
                msg += f"• {rt.name}: ⚠️ تعرفه ندارد\n"
            
            keyboard.append([{"text": rt.name, "callback_data": f"addcourse_rate_{rt.id}"}])
        
        keyboard.append([{"text": "⏭️ بدون تعرفه", "callback_data": "addcourse_rate_none"}])
        keyboard.append([{"text": "❌ بازگشت", "callback_data": "manage_courses"}])
        send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif step == 'ADD_COURSE_DURATION':
        if text_en.isdigit():
            state['duration'] = int(text_en)
            state['step'] = 'ADD_COURSE_FEE'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "💰 هزینه پایه (تومان) - فقط اگر استاد تعرفه ندارد:")
        else:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'ADD_COURSE_FEE':
        if text_en.isdigit():
            teacher = Teacher.objects.get(id=state['teacher_id'])
            rate_template = RateTemplate.objects.filter(id=state.get('rate_template_id')).first() if state.get('rate_template_id') else None
            
            course = Course.objects.create(
                name=state['course_name'],
                teacher=teacher,
                rate_template=rate_template,
                duration_minutes=state['duration'],
                base_fee=int(text_en) if text_en.isdigit() else 0
            )
            
            cache.delete(f"state_{chat_id}")
            
            msg = show_course_details(chat_id, course)
            keyboard = {
                "inline_keyboard": [
                    [{"text": "👥 هنرجویان", "callback_data": f"course_students_{course.id}"}],
                    [{"text": "➕ ثبت‌نام", "callback_data": f"course_enroll_{course.id}"}],
                    [{"text": "❌ بازگشت", "callback_data": "manage_courses"}]
                ]
            }
            send_bale_message(chat_id, "✅ کلاس ایجاد شد.\n\n" + msg, reply_markup=keyboard)
        else:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'ENROLL_STUDENT_SEARCH':
        students = Student.objects.filter(
            Q(first_name__icontains=text) | 
            Q(last_name__icontains=text) | 
            Q(phone_number__icontains=text_en)
        )[:10]
        
        if not students.exists():
            send_bale_message(chat_id, "❌ هنرجویی یافت نشد.")
            return
        
        msg = "🔍 **نتایج:**\n\n"
        keyboard = []
        for i, s in enumerate(students, 1):
            msg += f"{i}. {s.get_full_name()} - {s.phone_number}\n"
            keyboard.append([{"text": f"{i}. {s.get_full_name()}", "callback_data": f"enroll_student_{s.id}"}])
        
        keyboard.append([{"text": "❌ بازگشت", "callback_data": "manage_courses"}])
        send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif step == 'EDIT_COURSE_NAME':
        course = Course.objects.filter(id=state['course_id']).first()
        if course:
            course.name = text
            course.save()
            cache.delete(f"state_{chat_id}")
            msg = show_course_details(chat_id, course)
            send_bale_message(chat_id, "✅ نام کلاس ویرایش شد.\n\n" + msg, reply_markup=build_manager_menu())
    
    elif step == 'EDIT_COURSE_DURATION':
        if text_en.isdigit():
            course = Course.objects.filter(id=state['course_id']).first()
            if course:
                course.duration_minutes = int(text_en)
                course.save()
                cache.delete(f"state_{chat_id}")
                msg = show_course_details(chat_id, course)
                send_bale_message(chat_id, "✅ مدت جلسه ویرایش شد.\n\n" + msg, reply_markup=build_manager_menu())
        else:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'EDIT_COURSE_FEE':
        if text_en.isdigit():
            course = Course.objects.filter(id=state['course_id']).first()
            if course:
                course.base_fee = int(text_en)
                course.save()
                cache.delete(f"state_{chat_id}")
                msg = show_course_details(chat_id, course)
                send_bale_message(chat_id, "✅ هزینه ویرایش شد.\n\n" + msg, reply_markup=build_manager_menu())
        else:
            send_bale_message(chat_id, "❌ فقط عدد")
    
    elif step == 'COURSE_MESSAGE_TEXT':
        course = Course.objects.filter(id=state['course_id']).first()
        if course:
            enrollments = course.enrollments.filter(is_active=True)
            sent_count = 0
            
            for enrollment in enrollments:
                student = enrollment.student
                if notify_student(student, f"📨 **پیام از کلاس {course.name}:**\n\n{text}"):
                    sent_count += 1
            
            cache.delete(f"state_{chat_id}")
            send_bale_message(
                chat_id,
                f"✅ پیام به {sent_count} هنرجو ارسال شد.",
                reply_markup=build_manager_menu()
            )