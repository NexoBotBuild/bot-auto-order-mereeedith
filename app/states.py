"""State FSM untuk alur multi-langkah (aiogram)."""
from aiogram.fsm.state import State, StatesGroup


class AddProduct(StatesGroup):
    name = State()
    description = State()


class EditProduct(StatesGroup):
    name = State()
    description = State()


class AddVariant(StatesGroup):
    name = State()
    price = State()


class EditVariant(StatesGroup):
    name = State()
    price = State()


class Stocking(StatesGroup):
    """Admin mengirim stok bulk (dipisah baris baru)."""
    collecting = State()


class EditSetting(StatesGroup):
    value = State()


class Broadcast(StatesGroup):
    waiting = State()   # menunggu konten yang akan disiarkan
