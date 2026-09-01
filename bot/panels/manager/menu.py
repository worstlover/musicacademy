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
    
    # ============ مدیریت کلاس‌ها ============
    # مهم: ابتدا callback های خاص را چک کن
    if data.startswith("addcourse_rate_"):
        handle_course_special_callback(chat_id, data, state)
    
    elif data.startswith("editcourse_rate_"):
        handle_course_special_callback(chat_id, data, state)
    
    elif data.startswith("enroll_student_"):
        handle_course_special_callback(chat_id, data, state)
    
    elif data == "manage_courses":
        handle_course_callback(chat_id, data, state)
    
    elif data == "add_course":
        handle_course_callback(chat_id, data, state)
    
    elif data.startswith("addcourse_"):
        handle_course_callback(chat_id, data, state)
    
    elif data.startswith("course_"):
        handle_course_callback(chat_id, data, state)
    
    elif data.startswith("editcourse_"):
        handle_course_callback(chat_id, data, state)
    
    # ============ مدیریت هنرجویان ============
    elif data == "manage_students":
        handle_student_callback(chat_id, data, state)
    
    elif data == "search_student":
        handle_student_callback(chat_id, data, state)
    
    elif data == "add_student":
        handle_student_callback(chat_id, data, state)
    
    elif data.startswith("student_"):
        handle_student_callback(chat_id, data, state)
    
    # ============ مدیریت اساتید ============
    elif data == "manage_teachers":
        handle_teacher_callback(chat_id, data, state)
    
    elif data == "search_teacher":
        handle_teacher_callback(chat_id, data, state)
    
    elif data == "add_teacher":
        handle_teacher_callback(chat_id, data, state)
    
    elif data.startswith("teacher_"):
        handle_teacher_callback(chat_id, data, state)
    
    elif data.startswith("setrate_"):
        handle_teacher_callback(chat_id, data, state)
    
    elif data.startswith("newrate_"):
        handle_teacher_callback(chat_id, data, state)
    
    # ============ برنامه‌ریزی ============
    elif data == "weekly_planning":
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("weeknav_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("planday_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("teacher_sched_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("copy_sched_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("add_session_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("session_detail_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("edit_time_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("edit_dur_"):
        handle_schedule_callback(chat_id, data, state)
    
    elif data.startswith("del_sess_"):
        handle_schedule_callback(chat_id, data, state)
    
    # ============ شارژها ============
    elif data == "pending_charges":
        handle_charge_callback(chat_id, data, state)
    
    elif data.startswith("approve_charge_"):
        handle_charge_callback(chat_id, data, state)
    
    elif data.startswith("reject_charge_"):
        handle_charge_callback(chat_id, data, state)
    
    elif data.startswith("student_charge_"):
        handle_charge_callback(chat_id, data, state)
    
    elif data.startswith("stype_"):
        handle_charge_callback(chat_id, data, state)
    
    # ============ غیبت‌ها ============
    elif data == "absence_requests":
        handle_absence_callback(chat_id, data, state)
    
    elif data.startswith("absence_approve_"):
        handle_absence_callback(chat_id, data, state)
    
    elif data.startswith("absence_reject_"):
        handle_absence_callback(chat_id, data, state)
    
    # ============ جابجایی‌ها ============
    elif data == "swap_requests_list":
        handle_swap_callback(chat_id, data, state)
    
    elif data.startswith("manager_swap_approve_"):
        handle_swap_callback(chat_id, data, state)
    
    elif data.startswith("manager_swap_reject_"):
        handle_swap_callback(chat_id, data, state)
    
    # ============ تسویه ============
    elif data == "settle_teacher":
        handle_settlement_callback(chat_id, data, state)
    
    # ============ گزارش ============
    elif data == "financial_report":
        handle_report_callback(chat_id, data, state)
    
    elif data.startswith("student_fin_"):
        handle_report_callback(chat_id, data, state)
    
    elif data.startswith("teacher_fin_"):
        handle_report_callback(chat_id, data, state)
    
    # ============ تنظیمات ============
    elif data == "set_warning":
        cache.set(f"state_{chat_id}", {"step": "WARNING_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو:")
    
    elif data == "set_credit_limit":
        cache.set(f"state_{chat_id}", {"step": "CREDIT_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام هنرجو:")
    
    # ============ بازگشت ============
    elif data == "back_to_manager":
        cache.delete(f"state_{chat_id}")
        send_bale_message(chat_id, "📋 منوی مدیر:", reply_markup=build_manager_menu())
    
    # ============ خروج ============
    elif data == "logout":
        cache.delete(f"state_{chat_id}")
        cache.delete(f"manager_chat_{chat_id}")
        from ..keyboards import build_start_menu
        send_bale_message(chat_id, "👋 خروج موفق.", reply_markup=build_start_menu())


def handle_manager_text(chat_id, text, text_en, state):
    """روتر text های مدیر"""
    step = state.get('step', '') if state else ''
    
    # ============ کلاس‌ها ============
    if step.startswith('ADD_COURSE'):
        handle_course_text(chat_id, text, text_en, state)
    
    elif step.startswith('ENROLL'):
        handle_course_text(chat_id, text, text_en, state)
    
    elif step.startswith('EDIT_COURSE'):
        handle_course_text(chat_id, text, text_en, state)
    
    elif step.startswith('COURSE_MESSAGE'):
        handle_course_text(chat_id, text, text_en, state)
    
    # ============ هنرجو ============
    elif step.startswith('ADD_STUDENT'):
        handle_student_text(chat_id, text, text_en, state)
    
    elif step.startswith('EDIT_STUDENT'):
        handle_student_text(chat_id, text, text_en, state)
    
    elif step.startswith('EDIT_PARENT'):
        handle_student_text(chat_id, text, text_en, state)
    
    elif step.startswith('SEARCH_STUDENT'):
        handle_student_text(chat_id, text, text_en, state)
    
    elif step.startswith('WARNING'):
        handle_student_text(chat_id, text, text_en, state)
    
    elif step.startswith('CREDIT'):
        handle_student_text(chat_id, text, text_en, state)
    
    # ============ استاد ============
    elif step.startswith('ADD_TEACHER'):
        handle_teacher_text(chat_id, text, text_en, state)
    
    elif step.startswith('SEARCH_TEACHER'):
        handle_teacher_text(chat_id, text, text_en, state)
    
    elif step.startswith('SET_RATE'):
        handle_teacher_text(chat_id, text, text_en, state)
    
    elif step.startswith('NEW_RATE'):
        handle_teacher_text(chat_id, text, text_en, state)
    
    elif step.startswith('EDIT_COMMISSION'):
        handle_teacher_text(chat_id, text, text_en, state)
    
    # ============ برنامه‌ریزی ============
    elif step.startswith('PLAN_'):
        handle_schedule_text(chat_id, text, text_en, state)
    
    elif step.startswith('COPY_'):
        handle_schedule_text(chat_id, text, text_en, state)
    
    elif step.startswith('ADD_SESSION'):
        handle_schedule_text(chat_id, text, text_en, state)
    
    elif step.startswith('EDIT_SESSION'):
        handle_schedule_text(chat_id, text, text_en, state)
    
    # ============ شارژ ============
    elif step.startswith('CHARGE'):
        handle_charge_text(chat_id, text, text_en, state)
    
    # ============ تسویه ============
    elif step.startswith('SETTLE'):
        handle_settlement_text(chat_id, text, text_en, state)
    
    # ============ گزارش ============
    elif step.startswith('FINANCE'):
        handle_report_text(chat_id, text, text_en, state)
    
    elif step.startswith('STUDENT_FINANCE'):
        handle_report_text(chat_id, text, text_en, state)
    
    elif step.startswith('TEACHER_FINANCE'):
        handle_report_text(chat_id, text, text_en, state)