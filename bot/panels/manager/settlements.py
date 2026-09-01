from django.core.cache import cache
from django.db.models import Q

from core.models import Teacher, RateTemplate, TeacherRate
from ...utils import send_bale_message, process_settlement
from ...keyboards import build_manager_menu


def handle_settlement_callback(chat_id, data, state):
    """مدیریت callback های تسویه"""
    
    if data == "settle_teacher":
        cache.set(f"state_{chat_id}", {"step": "SETTLE_SELECT"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام استاد:")


def handle_settlement_text(chat_id, text, text_en, state):
    """مدیریت text های تسویه"""
    step = state.get('step', '') if state else ''
    
    if step == 'SETTLE_SELECT':
        teachers = Teacher.objects.filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text)
        )[:5]
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