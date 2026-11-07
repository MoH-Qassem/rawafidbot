"""FSM states for multi-step financial flows."""
from aiogram.fsm.state import State, StatesGroup


class ExpenseStates(StatesGroup):
    choosing_mode = State()
    choosing_currency = State()
    entering_amount = State()
    choosing_category = State()
    entering_description = State()
    confirming = State()


class DepositStates(StatesGroup):
    choosing_currency = State()
    entering_amount = State()
    entering_description = State()
    confirming = State()


class WithdrawalStates(StatesGroup):
    choosing_mode = State()
    choosing_currency = State()
    entering_amount = State()
    entering_purpose = State()
    entering_description = State()
    confirming = State()
    # settle advance
    choosing_advance = State()
    entering_expense_amount = State()
    entering_returned_amount = State()
    choosing_settle_category = State()
    entering_settle_description = State()
    confirming_settle = State()


class DebtStates(StatesGroup):
    choosing_debt = State()
    entering_amount = State()
    entering_description = State()
    confirming = State()


class ContributionStates(StatesGroup):
    menu = State()
    # create
    choosing_currency = State()
    entering_amount = State()
    choosing_members = State()
    entering_description = State()
    entering_due_date = State()
    confirming_create = State()
    # pay
    choosing_obligation = State()
    entering_pay_amount = State()
    confirming_pay = State()


class SettingsStates(StatesGroup):
    menu = State()
    editing_name = State()
    editing_title = State()


class ReportStates(StatesGroup):
    menu = State()


class RegistrationStates(StatesGroup):
    entering_display_name = State()
    entering_job_title = State()


class OnboardingStates(StatesGroup):
    waiting_custom_title = State()
    entering_display_name = State()
    choosing_job_title = State()
    entering_nickname = State()
    reviewing_profile = State()


class GroupOpStates(StatesGroup):
    collecting = State()
    confirming = State()


class RoleAdminStates(StatesGroup):
    menu = State()
    creating_name = State()
    creating_code = State()
    renaming = State()
    assigning_member = State()
    assigning_role = State()
    editing_role_perms = State()
