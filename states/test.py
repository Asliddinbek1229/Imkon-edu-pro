from aiogram.filters.state import StatesGroup, State


class Test(StatesGroup):
    Q1 = State()
    Q2 = State()


class RegistrationState(StatesGroup):
    first_name = State()
    last_name = State()
    phone = State()


class ProfileEditState(StatesGroup):
    value = State()


class PaymentReceiptState(StatesGroup):
    awaiting_receipt = State()


class CourseAdminState(StatesGroup):
    add_name = State()
    add_is_active = State()
    add_price = State()
    add_video_count = State()
    add_author = State()
    add_duration = State()
    add_target_exam = State()
    add_includes = State()
    add_access_type = State()
    add_link = State()
    add_sort_order = State()
    add_description = State()
    add_photo = State()
    edit_value = State()


class AdminSettingsState(StatesGroup):
    awaiting_content = State()


class AdminState(StatesGroup):
    are_you_sure = State()
    ask_ad_content = State()
