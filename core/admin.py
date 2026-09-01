from django.contrib import admin
from .models import (
    Student, Teacher, Course, StudentCourse, ClassSession,
    WalletTransaction, TeacherEarning, Settlement,
    RateTemplate, TeacherRate, SessionVerificationCode
)

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'phone_number', 'wallet_balance', 'is_blocked']
    search_fields = ['first_name', 'last_name', 'phone_number', 'national_code']
    list_filter = ['is_active', 'is_blocked']

@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'phone_number', 'specialization', 'commission_percent']
    search_fields = ['first_name', 'last_name', 'phone_number']
    list_filter = ['is_active']

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['name', 'teacher', 'rate_template', 'duration_minutes', 'base_fee']
    search_fields = ['name', 'teacher__first_name', 'teacher__last_name']

@admin.register(StudentCourse)
class StudentCourseAdmin(admin.ModelAdmin):
    list_display = ['student', 'course', 'enrollment_date']
    search_fields = ['student__first_name', 'student__last_name', 'course__name']

@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ['student', 'teacher', 'session_date', 'fee', 'status', 'verification_method']
    search_fields = ['student__first_name', 'student__last_name', 'teacher__first_name']
    list_filter = ['status', 'verification_method']

@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ['student', 'transaction_type', 'amount', 'status', 'created_at']
    search_fields = ['student__first_name', 'student__last_name']
    list_filter = ['transaction_type', 'status']

@admin.register(TeacherEarning)
class TeacherEarningAdmin(admin.ModelAdmin):
    list_display = ['teacher', 'session', 'amount', 'is_settled']
    list_filter = ['is_settled']

@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ['teacher', 'amount', 'settlement_type', 'status', 'due_date']
    list_filter = ['status', 'settlement_type']

@admin.register(RateTemplate)
class RateTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']

@admin.register(TeacherRate)
class TeacherRateAdmin(admin.ModelAdmin):
    list_display = ['teacher', 'rate_template', 'hourly_rate']

@admin.register(SessionVerificationCode)
class SessionVerificationCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'session', 'is_used', 'expires_at']