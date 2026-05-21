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


class CourseAdminState(StatesGroup):
    add_name = State()
    add_price = State()
    add_video_count = State()
    add_description = State()
    add_photo = State()
    add_link = State()
    edit_value = State()


class AdminState(StatesGroup):
    are_you_sure = State()
    ask_ad_content = State()
