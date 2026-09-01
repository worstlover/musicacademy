import jdatetime
from django.core.cache import cache
from django.utils import timezone

from core.models import SessionSwapRequest
from ...utils import send_bale_message, get_local_time
from ...keyboards import build_manager_menu


def handle_swap_callback(chat_id, data, state):
    """مدیریت callback های جابجایی"""
    
    if data == "swap_requests_list":
        swaps = SessionSwapRequest.objects.filter(status='pending').order_by('-created_at')[:20]
        if not swaps.exists():
            send_bale_message(chat_id, "🔄 درخواستی نیست.", reply_markup=build_manager_menu())
        else:
            for sw in swaps:
                local_dt = get_local_time(sw.current_session.session_date)
                msg = f"🔄 {sw.requesting_student.get_full_name()}\n"
                msg += f"📅 {jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d %H:%M')}\n"
                if sw.preferred_start and sw.preferred_end:
                    msg += f"⏰ {sw.preferred_start.strftime('%H:%M')} تا {sw.preferred_end.strftime('%H:%M')}\n"
                if sw.target_student:
                    msg += f"👤 با: {sw.target_student.get_full_name()}\n"
                else:
                    msg += "⏰ ساعت خالی\n"
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "✅", "callback_data": f"manager_swap_approve_{sw.id}"},
                         {"text": "❌", "callback_data": f"manager_swap_reject_{sw.id}"}]
                    ]
                }
                send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("manager_swap_approve_"):
        swap_id = int(data.split("_")[-1])
        sw = SessionSwapRequest.objects.filter(id=swap_id, status='pending').first()
        if sw:
            sw.status = 'accepted'
            sw.responded_at = timezone.now()
            sw.save()
            
            requester_chat = cache.get(f"student_chat_{sw.requesting_student.id}")
            if requester_chat:
                msg = "✅ جابجایی تایید شد!"
                if sw.preferred_start and sw.preferred_end:
                    msg += f"\n⏰ {sw.preferred_start.strftime('%H:%M')} تا {sw.preferred_end.strftime('%H:%M')}"
                send_bale_message(requester_chat, msg)
            
            send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("manager_swap_reject_"):
        swap_id = int(data.split("_")[-1])
        sw = SessionSwapRequest.objects.filter(id=swap_id, status='pending').first()
        if sw:
            sw.status = 'rejected'
            sw.responded_at = timezone.now()
            sw.save()
            
            requester_chat = cache.get(f"student_chat_{sw.requesting_student.id}")
            if requester_chat:
                send_bale_message(requester_chat, "❌ جابجایی رد شد.")
            
            send_bale_message(chat_id, "❌", reply_markup=build_manager_menu())