from aiogram.fsm.state import State, StatesGroup


class UploadState(StatesGroup):
    waiting_for_quality = State()
    signup_email = State()
    signup_password = State()
