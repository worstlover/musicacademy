import jdatetime
from django.core.cache import cache
from django.db.models import Sum

from core.models import Student, Teacher, WalletTransaction, TeacherEarning
from ...utils import send_bale_message
from ...keyboards import build_manager_menu


def handle_report_callback(chat_id, data, state):
    """مدیریت callback های گزارش"""
    
    if data == "financial_report":
        cache.set(f"state_{chat_id}", {"step": "FINANCE_START"}, timeout=600)
        send_bale_message(chat_id, "📅 از تاریخ:")
    
    elif data.startswith("student_fin_"):
        sid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "STUDENT_FINANCE_START", "student_id": sid}, timeout=600)
        send_bale_message(chat_id, "📅 از:")
    
    elif data.startswith("teacher_fin_"):
        tid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "TEACHER_FINANCE_START", "teacher_id": tid}, timeout=600)
        send_bale_message(chat_id, "📅 از:")


def handle_report_text(chat_id, text, text_en, state):
    """مدیریت text های گزارش"""
    step = state.get('step', '') if state else ''
    
    if step == 'FINANCE_START':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            state['start_date'] = jd.togregorian()
            state['step'] = 'FINANCE_END'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📅 تا:")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'FINANCE_END':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            end_date = jd.togregorian()
            revenue = WalletTransaction.objects.filter(
                transaction_type='credit', status='approved',
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum'] or 0
            debit = WalletTransaction.objects.filter(
                transaction_type='debit', status='approved',
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum'] or 0
            msg = f"📊 شارژ: {revenue:,}\n💳 کسر: {debit:,}\n📈 تراز: {revenue-debit:,}"
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'STUDENT_FINANCE_START':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            state['start_date'] = jd.togregorian()
            state['step'] = 'STUDENT_FINANCE_END'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📅 تا:")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'STUDENT_FINANCE_END':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            end_date = jd.togregorian()
            student = Student.objects.get(id=state['student_id'])
            transactions = student.wallet_transactions.filter(
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            )
            msg = f"📊 {student.get_full_name()}\n\n"
            for t in transactions:
                sign = "+" if t.transaction_type == 'credit' else "-"
                msg += f"{sign}{t.amount:,} - {t.description}\n"
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'TEACHER_FINANCE_START':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            state['start_date'] = jd.togregorian()
            state['step'] = 'TEACHER_FINANCE_END'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "📅 تا:")
        except:
            send_bale_message(chat_id, "❌")
    
    elif step == 'TEACHER_FINANCE_END':
        try:
            parts = text.split('/')
            y, m, d = map(int, parts)
            jd = jdatetime.date(y, m, d)
            end_date = jd.togregorian()
            teacher = Teacher.objects.get(id=state['teacher_id'])
            earnings = TeacherEarning.objects.filter(
                teacher=teacher,
                created_at__date__gte=state['start_date'],
                created_at__date__lte=end_date
            )
            msg = f"📊 {teacher.get_full_name()}\n\n"
            total = 0
            for e in earnings:
                msg += f"💰 {e.amount:,} - {e.session.student.get_full_name()}\n"
                total += e.amount
            msg += f"\n💵 مجموع: {total:,}"
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
        except:
            send_bale_message(chat_id, "❌")