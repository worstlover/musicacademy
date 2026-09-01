import json
import traceback

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.contrib.auth import authenticate

from core.models import Student, Teacher, WalletTransaction
from .keyboards import build_start_menu, build_student_menu, build_teacher_menu, build_manager_menu
from .utils import send_bale_message
# فقط import رو تغییر بده
from .panels import handle_student_callback, handle_student_text
from .panels import handle_teacher_callback, handle_teacher_text
from .panels import handle_manager_callback, handle_manager_text


@csrf_exempt
def bale_webhook(request):
    if request.method == 'GET':
        return JsonResponse({"status": "ok"})
    
    if request.method != 'POST':
        return JsonResponse({"status": "error"}, status=405)
    
    try:
        update = json.loads(request.body.decode('utf-8'))
        
        # ========== CALLBACK ==========
        if 'callback_query' in update:
            callback = update['callback_query']
            chat_id = callback['message']['chat']['id']
            data = callback['data']
            
            user_session = cache.get(f"session_{chat_id}")
            state = cache.get(f"state_{chat_id}")
            
            if data == "logout":
                cache.delete(f"session_{chat_id}")
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "👋", reply_markup=build_start_menu())
                return JsonResponse({"status": "ok"})
            
            if data == "cancel":
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "❌")
                return JsonResponse({"status": "ok"})
            
            if data == "back_to_manager":
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "📋", reply_markup=build_manager_menu())
                return JsonResponse({"status": "ok"})
            
            if not user_session:
                send_bale_message(chat_id, "⏰ /start")
                return JsonResponse({"status": "ok"})
            
            role = user_session.get('role')
            user_id = user_session.get('user_id')
            
            if role == 'student':
                student = Student.objects.filter(id=user_id).first()
                if student:
                    handle_student_callback(chat_id, data, student)
            
            elif role == 'teacher':
                teacher = Teacher.objects.filter(id=user_id).first()
                if teacher:
                    handle_teacher_callback(chat_id, data, teacher)
            
            elif role == 'manager':
                handle_manager_callback(chat_id, data, state)
            
            return JsonResponse({"status": "ok"})
        
        # ========== CONTACT ==========
        if 'message' in update and 'contact' in update['message']:
            chat_id = update['message']['chat']['id']
            phone = update['message']['contact']['phone_number']
            
            if phone.startswith('+98'):
                phone = '0' + phone[3:]
            elif phone.startswith('98'):
                phone = '0' + phone[2:]
            
            student = Student.objects.filter(phone_number=phone, is_active=True, is_blocked=False).first()
            if student:
                cache.set(f"session_{chat_id}", {"role": "student", "user_id": student.id}, timeout=43200)
                cache.set(f"student_chat_{student.id}", chat_id, timeout=43200)
                send_bale_message(chat_id, f"✅ {student.get_full_name()}", reply_markup=build_student_menu(student))
                return JsonResponse({"status": "ok"})
            
            teacher = Teacher.objects.filter(phone_number=phone, is_active=True).first()
            if teacher:
                cache.set(f"session_{chat_id}", {"role": "teacher", "user_id": teacher.id}, timeout=43200)
                cache.set(f"teacher_chat_{teacher.id}", chat_id, timeout=43200)
                send_bale_message(chat_id, f"✅ {teacher.get_full_name()}", reply_markup=build_teacher_menu(teacher))
                return JsonResponse({"status": "ok"})
            
            send_bale_message(chat_id, "❌ ثبت نشده.")
            return JsonResponse({"status": "ok"})
        
        # ========== TEXT ==========
        if 'message' in update and 'text' in update['message']:
            chat_id = update['message']['chat']['id']
            text = update['message']['text'].strip()
            text_en = text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
            
            if text == '/start':
                cache.delete(f"session_{chat_id}")
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "👋", reply_markup=build_start_menu())
                return JsonResponse({"status": "ok"})
            
            if text == "🔐 ورود مدیر":
                cache.set(f"state_{chat_id}", {"step": "MANAGER_USERNAME"}, timeout=600)
                send_bale_message(chat_id, "👤:")
                return JsonResponse({"status": "ok"})
            
            state = cache.get(f"state_{chat_id}")
            user_session = cache.get(f"session_{chat_id}")
            
            # لاگین مدیر
            if state and state.get('step') == 'MANAGER_USERNAME':
                state['username'] = text
                state['step'] = 'MANAGER_PASSWORD'
                cache.set(f"state_{chat_id}", state, timeout=600)
                send_bale_message(chat_id, "🔑:")
                return JsonResponse({"status": "ok"})
            
            if state and state.get('step') == 'MANAGER_PASSWORD':
                user = authenticate(username=state.get('username', ''), password=text)
                cache.delete(f"state_{chat_id}")
                if user and (user.is_superuser or user.is_staff):
                    cache.set(f"session_{chat_id}", {"role": "manager", "user_id": user.id}, timeout=43200)
                    send_bale_message(chat_id, "✅", reply_markup=build_manager_menu())
                else:
                    send_bale_message(chat_id, "❌", reply_markup=build_start_menu())
                return JsonResponse({"status": "ok"})
            
            if user_session:
                role = user_session.get('role')
                user_id = user_session.get('user_id')
                
                if role == 'student':
                    student = Student.objects.filter(id=user_id).first()
                    if student:
                        handle_student_text(chat_id, text, text_en, student, state)
                
                elif role == 'teacher':
                    teacher = Teacher.objects.filter(id=user_id).first()
                    if teacher:
                        handle_teacher_text(chat_id, text, text_en, teacher, state)
                
                elif role == 'manager':
                    handle_manager_text(chat_id, text, text_en, state)
        
        # ========== PHOTO ==========
        if 'message' in update and 'photo' in update['message']:
            chat_id = update['message']['chat']['id']
            state = cache.get(f"state_{chat_id}")
            
            if state and state.get('step') == 'CHARGE_RECEIPT':
                user_session = cache.get(f"session_{chat_id}")
                if user_session and user_session.get('role') == 'student':
                    student = Student.objects.get(id=user_session['user_id'])
                    file_id = update['message']['photo'][-1]['file_id']
                    
                    WalletTransaction.objects.create(
                        student=student,
                        transaction_type='credit',
                        amount=state.get('amount', 0),
                        description="شارژ (در انتظار تایید)",
                        status='pending',
                        payment_method='manual',
                        receipt_image=file_id
                    )
                    
                    cache.delete(f"state_{chat_id}")
                    send_bale_message(chat_id, "✅ رسید دریافت شد.", reply_markup=build_student_menu(student))
    
    except Exception as e:
        print(f"❌ [FATAL] {e}")
        traceback.print_exc()
        return JsonResponse({"status": "error"}, status=500)
    
    return JsonResponse({"status": "ok"})