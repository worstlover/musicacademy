from django.db.models import Sum
from core.models import Teacher, TeacherEarning


def build_start_menu():
    return {
        "keyboard": [
            [{"text": "🎵 ورود هنرجو", "request_contact": True}],
            [{"text": "👨‍🏫 ورود استاد", "request_contact": True}],
            [{"text": "🔐 ورود مدیر"}]
        ],
        "resize_keyboard": True
    }


def build_student_menu(student):
    keyboard = []
    
    if student.is_blocked:
        keyboard.append([{"text": "🔴 حساب مسدود", "callback_data": "blocked_info"}])
    
    # مالی
    keyboard.append([{"text": f"💰 موجودی: {student.wallet_balance:,} تومان", "callback_data": "wallet_info"}])
    keyboard.append([
        {"text": "➕ شارژ", "callback_data": "charge_wallet"},
        {"text": "📋 سوابق شارژ", "callback_data": "charge_history"}
    ])
    
    # جلسات
    keyboard.append([
        {"text": "🔑 کد جلسه", "callback_data": "generate_code"},
        {"text": "📅 جلسات من", "callback_data": "my_sessions"}
    ])
    
    # جابجایی
    keyboard.append([
        {"text": "🔄 درخواست جابجایی", "callback_data": "swap_request"},
        {"text": "📋 سوابق جابجایی", "callback_data": "swap_list"}
    ])
    
    # غیبت
    keyboard.append([
        {"text": "🏠 درخواست غیبت", "callback_data": "absence_request"},
        {"text": "📋 سوابق غیبت", "callback_data": "absence_list"}
    ])
    
    keyboard.append([{"text": "❌ خروج", "callback_data": "logout"}])
    
    return {"inline_keyboard": keyboard}


def build_teacher_menu(teacher):
    # محاسبه درآمد کل
    total_earned = TeacherEarning.objects.filter(
        teacher=teacher
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
    pending = teacher.pending_settlement
    
    keyboard = [
        [{"text": "🔑 ثبت کد جلسه", "callback_data": "code_checkin"}],
        [
            {"text": "📅 برنامه امروز", "callback_data": "today_schedule"},
            {"text": "📆 برنامه هفتگی", "callback_data": "weekly_schedule"}
        ],
        [{"text": f"💰 درآمد کل: {total_earned:,} تومان", "callback_data": "my_income"}],
        [{"text": f"💳 درخواست تسویه (طلب: {pending:,})", "callback_data": "settlement_request"}],
        [{"text": "📨 ارسال پیام به کلاس", "callback_data": "send_message_to_course"}],
        [{"text": "❌ خروج", "callback_data": "logout"}]
    ]
    return {"inline_keyboard": keyboard}


def build_manager_menu():
    keyboard = [
        [{"text": "🎵 مدیریت کلاس‌ها", "callback_data": "manage_courses"}],
        [
            {"text": "👤 مدیریت هنرجویان", "callback_data": "manage_students"},
            {"text": "👨‍🏫 مدیریت اساتید", "callback_data": "manage_teachers"}
        ],
        [{"text": "📅 برنامه‌ریزی هفتگی", "callback_data": "weekly_planning"}],
        [
            {"text": "🔄 درخواست‌های جابجایی", "callback_data": "swap_requests_list"},
            {"text": "🏠 درخواست‌های غیبت", "callback_data": "absence_requests"}
        ],
        [
            {"text": "✅ تایید شارژها", "callback_data": "pending_charges"},
            {"text": "💳 تسویه با استاد", "callback_data": "settle_teacher"}
        ],
        [
            {"text": "⏰ تنظیم هشدار", "callback_data": "set_warning"},
            {"text": "🚫 تنظیم ردلاین", "callback_data": "set_credit_limit"}
        ],
        [{"text": "📊 گزارش مالی", "callback_data": "financial_report"}],
        [{"text": "❌ خروج", "callback_data": "logout"}]
    ]
    return {"inline_keyboard": keyboard}


def build_student_detail_keyboard(student):
    """کیبورد جزئیات هنرجو در پنل مدیر"""
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🔴 مسدود کردن" if not student.is_blocked else "🟢 رفع مسدودی", 
                    "callback_data": f"student_block_{student.id}" if not student.is_blocked else f"student_unblock_{student.id}"
                },
                {
                    "text": "⚪ غیرفعال کردن" if student.is_active else "🟢 فعال کردن",
                    "callback_data": f"student_deactivate_{student.id}" if student.is_active else f"student_activate_{student.id}"
                }
            ],
            [
                {"text": "✏️ ویرایش", "callback_data": f"student_edit_{student.id}"},
                {"text": "👨‍👩‍👦 والدین", "callback_data": f"student_parent_{student.id}"}
            ],
            [
                {"text": "💰 شارژ", "callback_data": f"student_charge_{student.id}"},
                {"text": "📊 گزارش مالی", "callback_data": f"student_fin_{student.id}"}
            ],
            [
                {"text": "📅 جلسات", "callback_data": f"student_sessions_{student.id}"},
                {"text": "🔄 جابجایی‌ها", "callback_data": f"student_swaps_{student.id}"}
            ],
            [
                {"text": "🏠 غیبت‌ها", "callback_data": f"student_absences_{student.id}"}
            ],
            [
                {"text": "🗑️ حذف", "callback_data": f"student_del_{student.id}"},
                {"text": "❌ بازگشت", "callback_data": "manage_students"}
            ]
        ]
    }
    return keyboard


def build_settlement_type_keyboard():
    """کیبورد انتخاب نوع پرداخت تسویه"""
    return {
        "inline_keyboard": [
            [
                {"text": "💵 نقد", "callback_data": "stype_cash"},
                {"text": "📝 چک", "callback_data": "stype_check"}
            ],
            [
                {"text": "⏰ نسیه", "callback_data": "stype_credit"},
                {"text": "💳 کارت", "callback_data": "stype_card"}
            ]
        ]
    }