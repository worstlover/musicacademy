from django.core.cache import cache

from core.models import WalletTransaction, Student
from ...utils import send_bale_message, send_bale_photo
from ...keyboards import build_manager_menu


def handle_charge_callback(chat_id, data, state):
    """مدیریت callback های شارژ"""
    
    if data == "pending_charges":
        pending = WalletTransaction.objects.filter(
            transaction_type='credit', status='pending'
        )[:10]
        
        if not pending.exists():
            send_bale_message(chat_id, "✅ شارژی نیست.", reply_markup=build_manager_menu())
        else:
            for t in pending:
                msg = f"👤 {t.student.get_full_name()}\n💰 {t.amount:,}\n📅 {t.get_jalali_date()}\n"
                if t.receipt_image:
                    send_bale_photo(chat_id, t.receipt_image, msg)
                else:
                    send_bale_message(chat_id, msg + "⚠️ بدون عکس")
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "✅", "callback_data": f"approve_charge_{t.id}"},
                         {"text": "❌", "callback_data": f"reject_charge_{t.id}"}]
                    ]
                }
                send_bale_message(chat_id, "تصمیم:", reply_markup=keyboard)
    
    elif data.startswith("approve_charge_"):
        tid = int(data.split("_")[-1])
        t = WalletTransaction.objects.filter(id=tid, status='pending').first()
        if t:
            t.status = 'approved'
            t.save()
            
            # رفرش و رفع مسدودی
            student = t.student
            student.refresh_from_db()
            if student.is_blocked and student.wallet_balance >= student.credit_limit:
                student.is_blocked = False
                student.blocked_at = None
                student.save()
                student.refresh_from_db()
            
            sc = cache.get(f"student_chat_{student.id}")
            if sc:
                msg = f"✅ شارژ {t.amount:,} تایید شد!\n💰 موجودی: {student.wallet_balance:,}"
                send_bale_message(sc, msg)
            
            send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif data.startswith("reject_charge_"):
        tid = int(data.split("_")[-1])
        t = WalletTransaction.objects.filter(id=tid, status='pending').first()
        if t:
            t.status = 'rejected'
            t.save()
            sc = cache.get(f"student_chat_{t.student.id}")
            if sc:
                send_bale_message(sc, f"❌ شارژ {t.amount:,} رد شد.")
            send_bale_message(chat_id, "❌", reply_markup=build_manager_menu())
    
    elif data.startswith("student_charge_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "CHARGE_TYPE", "student_id": sid}, timeout=600)
        keyboard = {
            "inline_keyboard": [
                [{"text": "💵 نقد", "callback_data": "stype_cash"}],
                [{"text": "📝 چک", "callback_data": "stype_check"}],
                [{"text": "⏰ نسیه", "callback_data": "stype_credit"}]
            ]
        }
        send_bale_message(chat_id, "📋 نوع:", reply_markup=keyboard)
    
    elif data.startswith("stype_"):
        stype_map = {'stype_cash': 'cash', 'stype_check': 'check', 'stype_credit': 'credit'}
        state = state or {}
        state['charge_type'] = stype_map[data]
        state['step'] = 'CHARGE_AMOUNT'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "💰 مبلغ:")


def handle_charge_text(chat_id, text, text_en, state):
    """مدیریت text های شارژ"""
    step = state.get('step', '') if state else ''
    
    if step == 'CHARGE_AMOUNT':
        if text_en.isdigit():
            student = Student.objects.get(id=state['student_id'])
            ct = state.get('charge_type', 'cash')
            if ct in ['check', 'credit']:
                state['amount'] = int(text_en)
                state['step'] = 'CHARGE_DUE'
                cache.set(f"state_{chat_id}", state, timeout=600)
                send_bale_message(chat_id, "📅 سررسید:")
            else:
                WalletTransaction.objects.create(
                    student=student, transaction_type='credit',
                    amount=int(text_en), description=f"شارژ {ct}",
                    status='approved', payment_method=ct
                )
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
    
    elif step == 'CHARGE_DUE':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            student = Student.objects.get(id=state['student_id'])
            WalletTransaction.objects.create(
                student=student, transaction_type='credit',
                amount=state['amount'], description=f"شارژ - سررسید {text}",
                status='approved', payment_method=state.get('charge_type')
            )
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")