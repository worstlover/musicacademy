import re
from django.core.cache import cache
from django.db.models import Q, Sum

from core.models import Teacher, RateTemplate, TeacherRate, TeacherEarning
from ...utils import send_bale_message
from ...keyboards import build_manager_menu


def handle_teacher_callback(chat_id, data, state):
    """مدیریت callback های استاد در پنل مدیر"""
    
    if data == "manage_teachers":
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ ثبت استاد", "callback_data": "add_teacher"}],
                [{"text": "🔍 جستجو", "callback_data": "search_teacher"}],
                [{"text": "❌ بازگشت", "callback_data": "back_to_manager"}]
            ]
        }
        send_bale_message(chat_id, "👨‍🏫 مدیریت اساتید:", reply_markup=keyboard)
    
    elif data == "search_teacher":
        cache.set(f"state_{chat_id}", {"step": "SEARCH_TEACHER"}, timeout=600)
        send_bale_message(chat_id, "🔍 نام یا شماره:")
    
    elif data == "add_teacher":
        cache.set(f"state_{chat_id}", {"step": "ADD_TEACHER_NAME"}, timeout=600)
        send_bale_message(chat_id, "👨‍🏫 نام استاد:")
    
    elif data.startswith("teacher_detail_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            total_earned = TeacherEarning.objects.filter(teacher=t).aggregate(Sum('amount'))['amount__sum'] or 0
            total_settled = TeacherEarning.objects.filter(teacher=t, is_settled=True).aggregate(Sum('amount'))['amount__sum'] or 0
            
            msg = f"👨‍🏫 **{t.get_full_name()}**\n\n"
            msg += f"📱 موبایل: {t.phone_number}\n"
            msg += f"🎵 تخصص: {t.specialization}\n"
            msg += f"💯 درصد سهم: {t.commission_percent}%\n"
            msg += f"💰 کل درآمد: {total_earned:,} تومان\n"
            msg += f"✅ تسویه شده: {total_settled:,} تومان\n"
            msg += f"💳 طلبکار: {t.pending_settlement:,} تومان\n\n"
            
            msg += "📋 **تعرفه‌ها:**\n"
            rates = t.rates.select_related('rate_template').all()
            if rates.exists():
                for tr in rates:
                    msg += f"• {tr.rate_template.name}: {tr.hourly_rate:,} تومان/ساعت\n"
            else:
                msg += "⚠️ تعرفه‌ای ثبت نشده\n"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📅 برنامه", "callback_data": f"teacher_sched_{t.id}"}],
                    [{"text": "📋 تعرفه‌ها", "callback_data": f"teacher_rates_{t.id}"}],
                    [{"text": "💯 درصد سهم", "callback_data": f"teacher_comm_{t.id}"}],
                    [{"text": "📊 گزارش مالی", "callback_data": f"teacher_fin_{t.id}"}],
                    [{"text": "✏️ ویرایش", "callback_data": f"teacher_edit_{t.id}"}],
                    [{"text": "❌ بازگشت", "callback_data": "manage_teachers"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("teacher_edit_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            msg = f"✏️ **ویرایش {t.get_full_name()}**\n\n"
            msg += "چه چیزی را ویرایش می‌کنید؟"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📝 نام", "callback_data": f"teacher_edit_name_{t.id}"}],
                    [{"text": "📱 موبایل", "callback_data": f"teacher_edit_phone_{t.id}"}],
                    [{"text": "🎵 تخصص", "callback_data": f"teacher_edit_specialty_{t.id}"}],
                    [{"text": "💯 درصد", "callback_data": f"teacher_comm_{t.id}"}],
                    [{"text": "❌ بازگشت", "callback_data": f"teacher_detail_{t.id}"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif data.startswith("teacher_edit_name_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            cache.set(f"state_{chat_id}", {"step": "EDIT_TEACHER_NAME", "teacher_id": tid}, timeout=600)
            send_bale_message(chat_id, f"📝 نام جدید (فعلی: {t.get_full_name()}):")
    
    elif data.startswith("teacher_edit_phone_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            cache.set(f"state_{chat_id}", {"step": "EDIT_TEACHER_PHONE", "teacher_id": tid}, timeout=600)
            send_bale_message(chat_id, f"📱 موبایل جدید (فعلی: {t.phone_number}):")
    
    elif data.startswith("teacher_edit_specialty_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            cache.set(f"state_{chat_id}", {"step": "EDIT_TEACHER_SPECIALTY", "teacher_id": tid}, timeout=600)
            send_bale_message(chat_id, f"🎵 تخصص جدید (فعلی: {t.specialization}):")
    
    elif data.startswith("teacher_rates_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            rates = RateTemplate.objects.filter(is_active=True)
            
            msg = f"📋 **تعرفه‌های {t.get_full_name()}**\n\n"
            msg += "قالب‌های موجود:\n\n"
            
            keyboard = []
            for r in rates:
                # نمایش تعرفه فعلی استاد برای این قالب
                current_rate = TeacherRate.objects.filter(teacher=t, rate_template=r).first()
                if current_rate:
                    msg += f"• {r.name}: {current_rate.hourly_rate:,} تومان/ساعت\n"
                    label = f"✏️ {r.name} ({current_rate.hourly_rate:,})"
                else:
                    msg += f"• {r.name}: ⚠️ تعرفه ندارد\n"
                    label = f"➕ {r.name}"
                
                keyboard.append([{"text": label, "callback_data": f"setrate_{tid}_{r.id}"}])
            
            keyboard.append([{"text": "➕ قالب جدید", "callback_data": f"newrate_{tid}"}])
            keyboard.append([{"text": "❌ بازگشت", "callback_data": f"teacher_detail_{tid}"}])
            send_bale_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard})
    
    elif data.startswith("setrate_"):
        parts = data.split("_")
        tid = int(parts[1])
        rid = int(parts[2])
        
        teacher = Teacher.objects.filter(id=tid).first()
        rate_template = RateTemplate.objects.filter(id=rid).first()
        
        if teacher and rate_template:
            current_rate = TeacherRate.objects.filter(teacher=teacher, rate_template=rate_template).first()
            current_amount = current_rate.hourly_rate if current_rate else 0
            
            cache.set(f"state_{chat_id}", {"step": "SET_RATE", "teacher_id": tid, "rate_id": rid}, timeout=600)
            
            msg = f"📋 **{rate_template.name}**\n"
            msg += f"👨‍🏫 {teacher.get_full_name()}\n\n"
            
            if current_amount > 0:
                msg += f"💰 تعرفه فعلی: {current_amount:,} تومان/ساعت\n\n"
            
            msg += "مبلغ جدید (تومان/ساعت):"
            send_bale_message(chat_id, msg)
    
    elif data.startswith("newrate_"):
        tid = int(data.split("_")[-1])
        cache.set(f"state_{chat_id}", {"step": "NEW_RATE_NAME", "teacher_id": tid}, timeout=600)
        send_bale_message(chat_id, "📋 نام قالب تعرفه جدید:\n(مثال: گروهی ۵ نفره)")
    
    elif data.startswith("teacher_comm_"):
        tid = int(data.split("_")[-1])
        t = Teacher.objects.filter(id=tid).first()
        if t:
            cache.set(f"state_{chat_id}", {"step": "EDIT_COMMISSION", "teacher_id": tid}, timeout=600)
            send_bale_message(chat_id, f"💯 درصد سهم جدید (فعلی: {t.commission_percent}%):")


def handle_teacher_text(chat_id, text, text_en, state):
    """مدیریت text های استاد در پنل مدیر"""
    step = state.get('step', '') if state else ''
    
    if step == 'SEARCH_TEACHER':
        teachers = Teacher.objects.filter(
            Q(first_name__icontains=text) | 
            Q(last_name__icontains=text) | 
            Q(phone_number__icontains=text_en)
        )[:10]
        
        cache.delete(f"state_{chat_id}")
        
        if not teachers.exists():
            send_bale_message(chat_id, "❌ استادی یافت نشد", reply_markup=build_manager_menu())
        else:
            keyboard = []
            for t in teachers:
                keyboard.append([{"text": f"👨‍🏫 {t.get_full_name()}", "callback_data": f"teacher_detail_{t.id}"}])
            keyboard.append([{"text": "❌ بازگشت", "callback_data": "manage_teachers"}])
            send_bale_message(chat_id, "🔍 **نتایج جستجو:**", reply_markup={"inline_keyboard": keyboard})
    
    elif step == 'ADD_TEACHER_NAME':
        state['first_name'] = text
        state['step'] = 'ADD_TEACHER_LAST'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "نام خانوادگی:")
    
    elif step == 'ADD_TEACHER_LAST':
        state['last_name'] = text
        state['step'] = 'ADD_TEACHER_PHONE'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, "📱 شماره موبایل:\n(مثال: 09123456789)")
    
    elif step == 'ADD_TEACHER_PHONE':
        if re.match(r'^09\d{9}$', text_en):
            # چک تکراری نبودن
            existing = Teacher.objects.filter(phone_number=text_en).first()
            if existing:
                send_bale_message(chat_id, f"⚠️ استادی با این شماره وجود دارد:\n{existing.get_full_name()}")
                return
            
            state['phone'] = text_en
            state['step'] = 'ADD_TEACHER_SPECIALTY'
            cache.set(f"state_{chat_id}", state, timeout=600)
            send_bale_message(chat_id, "🎵 تخصص:\n(مثال: گیتار، پیانو، ویولن)")
        else:
            send_bale_message(chat_id, "❌ شماره نامعتبر.\nمثال: 09123456789")
    
    elif step == 'ADD_TEACHER_SPECIALTY':
        teacher = Teacher.objects.create(
            first_name=state['first_name'],
            last_name=state['last_name'],
            phone_number=state['phone'],
            specialization=text
        )
        
        cache.delete(f"state_{chat_id}")
        
        msg = f"✅ **استاد ثبت شد**\n\n"
        msg += f"👨‍🏫 {teacher.get_full_name()}\n"
        msg += f"📱 {teacher.phone_number}\n"
        msg += f"🎵 {teacher.specialization}\n"
        msg += f"💯 درصد سهم: {teacher.commission_percent}%\n\n"
        msg += "⚠️ فراموش نکنید تعرفه‌های استاد را تنظیم کنید."
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "📋 تنظیم تعرفه‌ها", "callback_data": f"teacher_rates_{teacher.id}"}],
                [{"text": "📋 جزئیات استاد", "callback_data": f"teacher_detail_{teacher.id}"}],
                [{"text": "❌ بازگشت", "callback_data": "manage_teachers"}]
            ]
        }
        send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif step == 'EDIT_TEACHER_NAME':
        t = Teacher.objects.filter(id=state['teacher_id']).first()
        if t:
            parts = text.split(' ')
            t.first_name = parts[0]
            t.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
            t.save()
            
            cache.delete(f"state_{chat_id}")
            msg = f"✅ نام ویرایش شد: {t.get_full_name()}"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "❌ بازگشت", "callback_data": f"teacher_detail_{t.id}"}]
                ]
            }
            send_bale_message(chat_id, msg, reply_markup=keyboard)
    
    elif step == 'EDIT_TEACHER_PHONE':
        t = Teacher.objects.filter(id=state['teacher_id']).first()
        if t:
            if re.match(r'^09\d{9}$', text_en):
                existing = Teacher.objects.filter(phone_number=text_en).exclude(id=t.id).first()
                if existing:
                    send_bale_message(chat_id, f"⚠️ این شماره برای {existing.get_full_name()} ثبت شده.")
                    return
                
                t.phone_number = text_en
                t.save()
                cache.delete(f"state_{chat_id}")
                send_bale_message(chat_id, "✅ موبایل ویرایش شد", reply_markup=build_manager_menu())
            else:
                send_bale_message(chat_id, "❌ شماره نامعتبر.\nمثال: 09123456789")
    
    elif step == 'EDIT_TEACHER_SPECIALTY':
        t = Teacher.objects.filter(id=state['teacher_id']).first()
        if t:
            t.specialization = text
            t.save()
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, "✅ تخصص ویرایش شد", reply_markup=build_manager_menu())
    
    elif step == 'SET_RATE':
        if text_en.isdigit():
            amount = int(text_en)
            
            if amount <= 0:
                send_bale_message(chat_id, "❌ مبلغ باید بیشتر از صفر باشد")
                return
            
            teacher = Teacher.objects.filter(id=state['teacher_id']).first()
            rate_template = RateTemplate.objects.filter(id=state['rate_id']).first()
            
            if teacher and rate_template:
                TeacherRate.objects.update_or_create(
                    teacher=teacher, 
                    rate_template=rate_template,
                    defaults={'hourly_rate': amount}
                )
                
                cache.delete(f"state_{chat_id}")
                send_bale_message(
                    chat_id, 
                    f"✅ تعرفه {rate_template.name} برای {teacher.get_full_name()}:\n"
                    f"💰 {amount:,} تومان/ساعت",
                    reply_markup=build_manager_menu()
                )
        else:
            send_bale_message(chat_id, "❌ فقط عدد وارد کنید")
    
    elif step == 'NEW_RATE_NAME':
        state['rate_name'] = text
        state['step'] = 'NEW_RATE_AMOUNT'
        cache.set(f"state_{chat_id}", state, timeout=600)
        send_bale_message(chat_id, f"📋 {text}\n\n💰 مبلغ (تومان/ساعت):")
    
    elif step == 'NEW_RATE_AMOUNT':
        if text_en.isdigit():
            amount = int(text_en)
            
            if amount <= 0:
                send_bale_message(chat_id, "❌ مبلغ باید بیشتر از صفر باشد")
                return
            
            # چک تکراری نبودن نام قالب
            existing_template = RateTemplate.objects.filter(name=state['rate_name']).first()
            
            if existing_template:
                # اگر قالب وجود دارد، فقط تعرفه استاد را ثبت کن
                TeacherRate.objects.update_or_create(
                    teacher_id=state['teacher_id'],
                    rate_template=existing_template,
                    defaults={'hourly_rate': amount}
                )
                msg = f"✅ تعرفه {existing_template.name} ثبت شد"
            else:
                # ایجاد قالب جدید
                rate_template = RateTemplate.objects.create(name=state['rate_name'])
                TeacherRate.objects.create(
                    teacher_id=state['teacher_id'],
                    rate_template=rate_template,
                    hourly_rate=amount
                )
                msg = f"✅ قالب {rate_template.name} ایجاد و تعرفه ثبت شد"
            
            cache.delete(f"state_{chat_id}")
            send_bale_message(chat_id, msg, reply_markup=build_manager_menu())
        else:
            send_bale_message(chat_id, "❌ فقط عدد وارد کنید")
    
    elif step == 'EDIT_COMMISSION':
        if text_en.isdigit():
            percent = int(text_en)
            
            if percent < 0 or percent > 100:
                send_bale_message(chat_id, "❌ درصد باید بین 0 تا 100 باشد")
                return
            
            t = Teacher.objects.filter(id=state['teacher_id']).first()
            if t:
                t.commission_percent = percent
                t.save()
                
                cache.delete(f"state_{chat_id}")
                send_bale_message(
                    chat_id, 
                    f"✅ درصد سهم {t.get_full_name()}: {percent}%",
                    reply_markup=build_manager_menu()
                )
        else:
            send_bale_message(chat_id, "❌ فقط عدد وارد کنید")