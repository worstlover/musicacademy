from django.db import models
from django.utils import timezone
import jdatetime
import random

MUSIC_QUOTES = [
    "موسیقی زبان روح است 🎵",
    "هر نت، قدمی به سوی آرامش است 🎶",
    "موسیقی، شعر بی‌کلام قلب‌هاست 💝",
    "زندگی بدون موسیقی اشتباه است 🎼",
    "نت‌ها پرواز می‌دهند روح را 🕊️",
    "موسیقی، داروی روح است ✨",
    "هر آهنگی، داستانی ناگفته دارد 📖",
    "صدای موسیقی، صدای زندگی است 🌟",
]

def get_random_quote():
    return random.choice(MUSIC_QUOTES)


class Student(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    national_code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=15, unique=True)
    parent_name = models.CharField(max_length=100, null=True, blank=True)
    parent_phone = models.CharField(max_length=15, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    face_encodings = models.JSONField(default=list, blank=True)
    
    warning_interval_hours = models.PositiveIntegerField(default=24)
    last_warning_sent = models.DateTimeField(null=True, blank=True)
    warning_enabled = models.BooleanField(default=True)
    
    credit_limit = models.IntegerField(default=0, verbose_name="رد لاین (سقف بدهی)")
    is_blocked = models.BooleanField(default=False)
    blocked_at = models.DateTimeField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "هنرجو"
        verbose_name_plural = "هنرجویان"
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def wallet_balance(self):
        total_credit = self.wallet_transactions.filter(
            transaction_type='credit', status='approved'
        ).aggregate(models.Sum('amount'))['amount__sum'] or 0
        total_debit = self.wallet_transactions.filter(
            transaction_type='debit', status='approved'
        ).aggregate(models.Sum('amount'))['amount__sum'] or 0
        return total_credit - total_debit
    
    @property
    def last_session_fee(self):
        last_session = self.sessions.filter(status='confirmed').order_by('-session_date').first()
        if last_session:
            return last_session.fee
        enrollment = self.enrollments.filter(is_active=True).first()
        if enrollment:
            return enrollment.course.base_fee
        return 50000
    
    @property
    def remaining_sessions(self):
        fee = self.last_session_fee
        if fee <= 0:
            return 0
        return max(0, self.wallet_balance // fee)
    
    def check_credit_limit(self):
        if self.wallet_balance < self.credit_limit:
            if not self.is_blocked:
                self.is_blocked = True
                self.blocked_at = timezone.now()
                self.save()
                return True
        elif self.is_blocked and self.wallet_balance >= self.credit_limit:
            self.is_blocked = False
            self.blocked_at = None
            self.save()
        return False
    
    def should_send_warning(self):
        if not self.warning_enabled or self.is_blocked:
            return False
        if self.wallet_balance >= self.last_session_fee:
            return False
        if not self.last_warning_sent:
            return True
        hours_passed = (timezone.now() - self.last_warning_sent).total_seconds() / 3600
        return hours_passed >= self.warning_interval_hours


class Teacher(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    national_code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=15, unique=True)
    specialization = models.CharField(max_length=100, verbose_name="تخصص/ساز")
    
    commission_percent = models.PositiveIntegerField(default=30, verbose_name="درصد سهم استاد")
    initial_balance = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "استاد"
        verbose_name_plural = "اساتید"
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def calculate_teacher_share(self, session_fee):
        return int(session_fee * self.commission_percent / 100)
    
    @property
    def total_earned(self):
        return TeacherEarning.objects.filter(
            teacher=self, is_settled=True
        ).aggregate(models.Sum('amount'))['amount__sum'] or 0
    
    @property
    def pending_settlement(self):
        return TeacherEarning.objects.filter(
            teacher=self, is_settled=False
        ).aggregate(models.Sum('amount'))['amount__sum'] or 0


class RateTemplate(models.Model):
    """قالب تعرفه - مثلاً انفرادی، گروهی ۳ نفره، گروهی ۵ نفره"""
    name = models.CharField(max_length=100, unique=True, verbose_name="نام تعرفه")
    description = models.TextField(null=True, blank=True, verbose_name="توضیحات")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "قالب تعرفه"
        verbose_name_plural = "قالب‌های تعرفه"
    
    def __str__(self):
        return self.name


class TeacherRate(models.Model):
    """تعرفه هر استاد برای هر قالب"""
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='rates')
    rate_template = models.ForeignKey(RateTemplate, on_delete=models.CASCADE, related_name='teacher_rates')
    hourly_rate = models.PositiveIntegerField(verbose_name="تعرفه ساعتی (تومان)")
    
    class Meta:
        verbose_name = "تعرفه استاد"
        verbose_name_plural = "تعرفه‌های اساتید"
        unique_together = ('teacher', 'rate_template')
    
    def __str__(self):
        return f"{self.teacher.get_full_name()} - {self.rate_template.name}: {self.hourly_rate:,}"
    
    def calculate_fee(self, duration_minutes):
        """محاسبه هزینه بر اساس مدت"""
        return (self.hourly_rate * duration_minutes) // 60


class Course(models.Model):
    name = models.CharField(max_length=200, verbose_name="نام کلاس")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='courses')
    rate_template = models.ForeignKey(
        RateTemplate, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="قالب تعرفه"
    )
    duration_minutes = models.PositiveIntegerField(default=60, verbose_name="مدت هر جلسه (دقیقه)")
    base_fee = models.PositiveIntegerField(
        default=0, 
        verbose_name="هزینه پایه (اختیاری - اگر تعرفه استاد نبود)"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "کلاس"
        verbose_name_plural = "کلاس‌ها"
    
    def __str__(self):
        return f"{self.name} - {self.teacher.get_full_name()}"
    
    def get_current_fee(self, duration_minutes=None):
        """
        دریافت هزینه جلسه
        اولویت: TeacherRate > base_fee
        """
        if not duration_minutes:
            duration_minutes = self.duration_minutes
        
        # ✅ اولویت با TeacherRate
        if self.rate_template:
            teacher_rate = TeacherRate.objects.filter(
                teacher=self.teacher,
                rate_template=self.rate_template
            ).first()
            if teacher_rate:
                return teacher_rate.calculate_fee(duration_minutes), teacher_rate
        
        # ✅ اگر TeacherRate نبود، از base_fee
        if self.base_fee > 0:
            return (self.base_fee * duration_minutes) // 60, None
        
        # ✅ حداقل مبلغ
        return 50000 * duration_minutes // 60, None
    
    def calculate_fee(self, duration_minutes=None):
        """محاسبه هزینه - سازگار با کد قبلی"""
        fee, _ = self.get_current_fee(duration_minutes)
        return fee
    
    def get_fee_details(self):
        """دریافت جزئیات کامل هزینه"""
        fee, teacher_rate = self.get_current_fee()
        
        if teacher_rate:
            return {
                'fee': fee,
                'hourly_rate': teacher_rate.hourly_rate,
                'rate_template': teacher_rate.rate_template,
                'source': 'teacher_rate'
            }
        else:
            return {
                'fee': fee,
                'hourly_rate': self.base_fee,
                'rate_template': None,
                'source': 'base_fee'
            }


class StudentCourse(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrollment_date = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "ثبت‌نام"
        verbose_name_plural = "ثبت‌نام‌ها"
        unique_together = ('student', 'course')


class ClassSession(models.Model):
    STATUS_CHOICES = [
        ('pending', 'در انتظار'),
        ('confirmed', 'تایید شده'),
        ('cancelled', 'لغو شده'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='sessions')
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='sessions')
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True)
    
    duration_minutes = models.PositiveIntegerField(default=60)
    session_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    fee = models.PositiveIntegerField()
    
    verification_method = models.CharField(max_length=20, choices=[
    ('face', 'تشخیص چهره'),
    ('code', 'کد تایید'),
    ('manual', 'دستی'),
    ('absent_authorized', 'غیبت موجه'),
    ('absent_unauthorized', 'غیبت غیرموجه'),
     ], default='face')
    
    face_verified = models.BooleanField(default=False)
    face_match_score = models.FloatField(null=True, blank=True)
    check_in_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "جلسه"
        verbose_name_plural = "جلسات"
        ordering = ['-session_date']
    
    def get_jalali_date(self):
        return jdatetime.datetime.fromgregorian(datetime=self.session_date).strftime('%Y/%m/%d %H:%M')
    
    def mark_confirmed(self, method='manual', face_score=None):
        self.status = 'confirmed'
        self.verification_method = method
        if face_score:
            self.face_match_score = face_score
        self.check_in_time = timezone.now()
        self.save()
        
        WalletTransaction.objects.create(
            student=self.student,
            transaction_type='debit',
            amount=self.fee,
            description=f"هزینه جلسه با {self.teacher.get_full_name()}",
            status='approved',
            session=self
        )
        
        teacher_share = self.teacher.calculate_teacher_share(self.fee)
        TeacherEarning.objects.create(
            teacher=self.teacher,
            session=self,
            amount=teacher_share
        )
        
        self.student.check_credit_limit()
        return self


class SessionVerificationCode(models.Model):
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='verification_codes')
    code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False)
    
    def is_valid(self):
        return not self.is_used and self.expires_at > timezone.now()


class WalletTransaction(models.Model):
    TYPE_CHOICES = [
        ('credit', 'شارژ'),
        ('debit', 'کسر'),
        ('refund', 'بازگشت'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'در انتظار'),
        ('approved', 'تایید شده'),
        ('rejected', 'رد شده'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='wallet_transactions')
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    amount = models.PositiveIntegerField()
    description = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    session = models.ForeignKey(ClassSession, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(max_length=20, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)
    receipt_image = models.CharField(max_length=255, null=True, blank=True, verbose_name="شناسه عکس رسید")
    class Meta:
        verbose_name = "تراکنش"
        verbose_name_plural = "تراکنش‌ها"
        ordering = ['-created_at']
    
    def get_jalali_date(self):
        return jdatetime.datetime.fromgregorian(datetime=self.created_at).strftime('%Y/%m/%d %H:%M')


class TeacherEarning(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='earnings')
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE)
    amount = models.PositiveIntegerField()
    is_settled = models.BooleanField(default=False)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "درآمد استاد"
        verbose_name_plural = "درآمدهای اساتید"


class Settlement(models.Model):
    SETTLEMENT_TYPE_CHOICES = [
        ('cash', 'نقد'),
        ('check', 'چک'),
        ('promissory', 'سفته'),
        ('credit', 'نسیه'),
        ('card', 'کارت به کارت'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'در انتظار'),
        ('paid', 'پرداخت شده'),
        ('overdue', 'سررسید گذشته'),
    ]
    
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='settlements')
    amount = models.PositiveIntegerField()
    settlement_type = models.CharField(max_length=20, choices=SETTLEMENT_TYPE_CHOICES, default='cash')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    due_date = models.DateField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    warning_sent = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = "تسویه"
        verbose_name_plural = "تسویه‌ها"
        ordering = ['-created_at']
    
    def is_overdue(self):
        if self.due_date and self.status == 'pending':
            return self.due_date < timezone.now().date()
        return False

class SessionSwapRequest(models.Model):
    """درخواست جابجایی کلاس"""
    STATUS_CHOICES = [
        ('pending', 'در انتظار'),
        ('accepted', 'پذیرفته شده'),
        ('rejected', 'رد شده'),
        ('expired', 'منقضی'),
    ]
    
    requesting_student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='swap_requests_sent')
    current_session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='swap_from')
    
    # هنرجوی هدف که قراره جابجا بشه
    target_student = models.ForeignKey(
        Student, 
        on_delete=models.CASCADE, 
        related_name='swap_requests_received',
        null=True, 
        blank=True,
        verbose_name="هنرجوی هدف"
    )
    
    # جلسه هدف
    target_session = models.ForeignKey(
        ClassSession, 
        on_delete=models.CASCADE, 
        related_name='swap_to',
        null=True, 
        blank=True,
        verbose_name="جلسه هدف"
    )
    
    # زمان‌های پیشنهادی
    preferred_start = models.TimeField(null=True, blank=True, verbose_name="از ساعت")
    preferred_end = models.TimeField(null=True, blank=True, verbose_name="تا ساعت")
    preferred_times = models.JSONField(default=list, blank=True, verbose_name="ساعت‌های پیشنهادی")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "درخواست جابجایی"
        verbose_name_plural = "درخواست‌های جابجایی"
    
    def __str__(self):
        return f"{self.requesting_student} - {self.current_session}"
    
    def is_on_time(self):
        """چک ۱۸ ساعت قبل"""
        if self.current_session and self.current_session.session_date:
            time_diff = self.current_session.session_date - self.created_at
            return time_diff.total_seconds() >= 12 * 3600
        return False


class AbsenceRequest(models.Model):
    """درخواست غیبت با مجوز"""
    STATUS_CHOICES = [
        ('pending', 'در انتظار تایید'),
        ('approved', 'تایید شده'),
        ('rejected', 'رد شده'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='absence_requests')
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='absence_requests')
    reason = models.TextField(verbose_name="دلیل غیبت")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "درخواست غیبت"
        verbose_name_plural = "درخواست‌های غیبت"
    
    def __str__(self):
        return f"{self.student} - {self.session}"
    
    @property
    def is_on_time(self):
        """چک کن ۱۲ ساعت قبل از کلاس درخواست داده"""
        time_diff = self.session.session_date - self.created_at
        return time_diff.total_seconds() >= 12 * 3600        