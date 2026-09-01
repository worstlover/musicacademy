from .menu import handle_manager_callback, handle_manager_text
from django.core.cache import cache

from ...utils import send_bale_message
from ...keyboards import build_manager_menu

from .students import handle_student_callback, handle_student_text
from .teachers import handle_teacher_callback, handle_teacher_text
from .schedule import handle_schedule_callback, handle_schedule_text
from .charges import handle_charge_callback, handle_charge_text
from .absences import handle_absence_callback
from .swaps import handle_swap_callback
from .settlements import handle_settlement_callback, handle_settlement_text
from .reports import handle_report_callback, handle_report_text
from .courses import handle_course_callback, handle_course_text, handle_course_special_callback


def handle_manager_callback(chat_id, data, state):
    """روتر callback های مدیر"""
    
    # مدیریت کلاس‌ها
    if data in ["manage_courses", "add_course"] or data.startswith(("course_", "addcourse_")):
        handle_course_callback(chat_id, data, state)
    
    # مدیریت هنرجویان
    elif data in ["manage_students", "search_student", "add_student"] or data.startswith("student_"):
        handle_student_callback(chat_id, data, state)
    
    # مدیریت اساتید
    elif data in ["manage_teachers", "search_teacher", "add_teacher"] or data.startswith("teacher_"):
        handle_teacher_callback(chat_id, data, state)
    
    # برنامه‌ریزی
    elif data in ["weekly_planning"] or data.startswith(("weeknav_", "planday_", "teacher_sched_", "copy_sched_", "add_session_", "session_detail_", "edit_time_", "edit_dur_", "del_sess_")):
        handle_schedule_callback(chat_id, data, state)
    
    # شارژها
    elif data == "pending_charges" or data.startswith(("approve_charge_", "reject_charge_", "student_charge_", "stype_")):
        handle_charge_callback(chat_id, data, state)
    
    # غیبت‌ها
    elif data == "absence_requests" or data.startswith(("absence_approve_", "absence_reject_")):
        handle_absence_callback(chat_id, data, state)
    
    # جابجایی‌ها
    elif data == "swap_requests_list" or data.startswith(("manager_swap_approve_", "manager_swap_reject_")):
        handle_swap_callback(chat_id, data, state)
    
    # تسویه
    elif data == "settle_teacher":
        handle_settlement_callback(chat_id, data, state)
    
    # گزارش
    elif data == "financial_report" or data.startswith(("student_fin_", "teacher_fin_")):
        handle_report_callback(chat_id, data, state)
    
    # callback های خاص کلاس
    elif data.startswith(("addcourse_rate_", "enroll_student_")):
        handle_course_special_callback(chat_id, data, state)
    
    # تنظیمات
    elif data == "set_warning":
        cache.set(f"state_{chat_id}", {"step": "WARNING_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو:")
    
    elif data == "set_credit_limit":
        cache.set(f"state_{chat_id}", {"step": "CREDIT_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو:")


def handle_manager_text(chat_id, text, text_en, state):
    """روتر text های مدیر"""
    step = state.get('step', '') if state else ''
    
    # کلاس‌ها
    if step.startswith(('ADD_COURSE', 'ENROLL', 'EDIT_COURSE')):
        handle_course_text(chat_id, text, text_en, state)
    
    # هنرجو
    elif step.startswith(('ADD_STUDENT', 'EDIT_STUDENT', 'EDIT_PARENT', 'SEARCH_STUDENT', 'WARNING', 'CREDIT')):
        handle_student_text(chat_id, text, text_en, state)
    
    # استاد
    elif step.startswith(('ADD_TEACHER', 'SEARCH_TEACHER', 'SET_RATE', 'NEW_RATE', 'EDIT_COMMISSION')):
        handle_teacher_text(chat_id, text, text_en, state)
    
    # برنامه‌ریزی
    elif step.startswith(('PLAN_', 'COPY_', 'ADD_SESSION', 'EDIT_SESSION')):
        handle_schedule_text(chat_id, text, text_en, state)
    
    # شارژ
    elif step.startswith('CHARGE'):
        handle_charge_text(chat_id, text, text_en, state)
    
    # تسویه
    elif step.startswith('SETTLE'):
        handle_settlement_text(chat_id, text, text_en, state)
    
    # گزارش
    elif step.startswith(('FINANCE', 'STUDENT_FINANCE', 'TEACHER_FINANCE')):
        handle_report_text(chat_id, text, text_en, state)