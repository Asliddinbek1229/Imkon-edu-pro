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
    add_video = State()
    edit_value = State()


class AdminSettingsState(StatesGroup):
    awaiting_content = State()


class AdminState(StatesGroup):
    are_you_sure = State()
    ask_ad_content = State()


class SupportState(StatesGroup):
    waiting_message = State()


class AdminBroadcastState(StatesGroup):
    collect_text = State()
    collect_photo = State()
    collect_video = State()
    collect_video_after_photo = State()
    collect_caption = State()
    collect_group = State()


class CouponState(StatesGroup):
    enter_code = State()


class AdminCouponState(StatesGroup):
    enter_code = State()
    enter_name = State()
    enter_discount_value = State()
    enter_max_uses = State()
    enter_expires = State()
    enter_course = State()
    edit_code = State()
    edit_name = State()
    edit_discount = State()
    edit_max_uses = State()
    edit_expires = State()
    edit_course = State()
