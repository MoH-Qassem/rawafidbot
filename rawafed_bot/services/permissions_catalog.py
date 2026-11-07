"""Canonical permission codes used across services and UI."""

# Operational
VIEW_CASHBOX = "view_cashbox"
RECORD_EXPENSE = "record_expense"
RECORD_DEPOSIT = "record_deposit"
RECORD_WITHDRAWAL = "record_withdrawal"
VIEW_DEBTS = "view_debts"
VIEW_MEMBERS = "view_members"
VIEW_HISTORY = "view_history"
EDIT_OWN_OPERATIONS = "edit_own_operations"
REVERSE_OPERATIONS = "reverse_operations"
VIEW_REPORTS = "view_reports"
EXPORT_EXCEL = "export_excel"
MANAGE_ADVANCES = "manage_advances"
CREATE_CONTRIBUTION = "create_contribution"
PAY_CONTRIBUTION = "pay_contribution"

# Admin
MANAGE_MEMBERS = "manage_members"
MANAGE_ROLES = "manage_roles"
MANAGE_SETTINGS = "manage_settings"
BACKUP = "backup"

ALL_PERMISSIONS = [
    (VIEW_CASHBOX, "عرض حالة الصندوق", "عمليات"),
    (RECORD_EXPENSE, "تسجيل المصروفات", "عمليات"),
    (RECORD_DEPOSIT, "تسجيل الإيداعات", "عمليات"),
    (RECORD_WITHDRAWAL, "تسجيل السحوبات", "عمليات"),
    (VIEW_DEBTS, "عرض الديون والمستحقات", "عمليات"),
    (VIEW_MEMBERS, "عرض حسابات الأعضاء", "عمليات"),
    (VIEW_HISTORY, "عرض سجل العمليات", "عمليات"),
    (EDIT_OWN_OPERATIONS, "تعديل العمليات التي سجلها العضو", "عمليات"),
    (REVERSE_OPERATIONS, "إلغاء العمليات", "عمليات"),
    (VIEW_REPORTS, "عرض التقارير", "تقارير"),
    (EXPORT_EXCEL, "تصدير Excel", "تقارير"),
    (MANAGE_ADVANCES, "إدارة العهد", "عمليات"),
    (CREATE_CONTRIBUTION, "إنشاء طلبات المساهمات", "مساهمات"),
    (PAY_CONTRIBUTION, "تسديد المساهمات", "مساهمات"),
    (MANAGE_MEMBERS, "إدارة الأعضاء", "إدارة"),
    (MANAGE_ROLES, "إدارة المناصب والصلاحيات", "إدارة"),
    (MANAGE_SETTINGS, "إدارة إعدادات البوت", "إدارة"),
    (BACKUP, "النسخ الاحتياطي", "إدارة"),
]

# Default equal member ops; CEO-only extras listed separately.
MEMBER_DEFAULT_PERMISSIONS = [
    VIEW_CASHBOX, RECORD_EXPENSE, RECORD_DEPOSIT, RECORD_WITHDRAWAL,
    VIEW_DEBTS, VIEW_MEMBERS, VIEW_HISTORY, EDIT_OWN_OPERATIONS,
    REVERSE_OPERATIONS, VIEW_REPORTS, EXPORT_EXCEL, MANAGE_ADVANCES,
    PAY_CONTRIBUTION,
]

CEO_ONLY_PERMISSIONS = [
    CREATE_CONTRIBUTION, MANAGE_MEMBERS, MANAGE_ROLES, MANAGE_SETTINGS, BACKUP,
]

CEO_LOCKED_PERMISSIONS = set(CEO_ONLY_PERMISSIONS) | {
    VIEW_CASHBOX, RECORD_EXPENSE, RECORD_DEPOSIT, RECORD_WITHDRAWAL,
    VIEW_DEBTS, VIEW_MEMBERS, VIEW_HISTORY, REVERSE_OPERATIONS,
    VIEW_REPORTS, EXPORT_EXCEL, MANAGE_ADVANCES, PAY_CONTRIBUTION,
}

DEFAULT_ROLES = [
    ("ceo", "CEO", True),
    ("finance_manager", "مدير مالي", True),
    ("accountant", "محاسب", True),
    ("board_member", "عضو مجلس إدارة", True),
]
