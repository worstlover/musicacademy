import jdatetime
from django.core.cache import cache
from django.utils import timezone

from core.models import AbsenceRequest
from ...utils import send_bale_message, get_local_time
from ...keyboards import build_manager_menu


def handle_absence_callback(chat_id, data, state):
    """مدیریت callback های غیبت"""
    
    if data == "absence_requests":
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
                        [{"text": "✅", "callback_data": f"absence_approve_{a.id}"},
                         {"text": "❌", "callback_data": f"absence_reject_{a.id}"}]
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
                send_bale_message(sc, "✅ غیبت تایید شد.")
            send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("absence_reject_"):
        aid = int(data.split("_")[-1])
        a = AbsenceRequest.objects.filter(id=aid, status='pending').first()
        if a:
            a.status = 'rejected'
            a.save()
            sc = cache.get(f"student_chat_{a.student.id}")
            if sc:
                send_bale_message(sc, "❌ غیبت رد شد.")
            send_bale_message(chat_id, "❌", reply_markup=build_manager_menu())