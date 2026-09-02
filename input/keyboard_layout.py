import ctypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_INPUTLANGCHANGEREQUEST = 0x0050
KLF_ACTIVATE = 0x00000001


def get_foreground_keyboard_layout():
    """Keyboard Layout پنجره فعال را برمی‌گرداند."""

    hwnd = user32.GetForegroundWindow()

    thread_id = user32.GetWindowThreadProcessId(
        hwnd,
        None
    )

    return user32.GetKeyboardLayout(thread_id)


def get_persian_keyboard_layout():
    """
    پیدا کردن Keyboard Layout فارسی که در Windows نصب شده.
    """

    count = user32.GetKeyboardLayoutList(0, None)

    if count <= 0:
        raise RuntimeError("هیچ Keyboard Layout پیدا نشد.")

    layouts = (ctypes.c_void_p * count)()

    user32.GetKeyboardLayoutList(
        count,
        layouts
    )

    for layout in layouts:

        hkl = int(layout)

        # Language ID از HKL
        lang_id = hkl & 0xFFFF

        # 0x0429 = Persian
        if lang_id == 0x0429:
            return hkl

    raise RuntimeError(
        "Persian Keyboard Layout روی Windows نصب نیست."
    )


def activate_persian_keyboard():

    hwnd = user32.GetForegroundWindow()

    if not hwnd:
        raise RuntimeError(
            "پنجره فعال پیدا نشد."
        )

    # پیدا کردن فارسی واقعی نصب‌شده
    persian_hkl = get_persian_keyboard_layout()

    # درخواست تغییر Layout برای پنجره فعال
    result = user32.PostMessageW(
        hwnd,
        WM_INPUTLANGCHANGEREQUEST,
        0,
        persian_hkl
    )

    if not result:
        raise OSError(
            ctypes.get_last_error()
        )

    return True

def activate_keyboard_layout(hkl):
    """
    فعال کردن یک Keyboard Layout مشخص
    """

    result = user32.ActivateKeyboardLayout(
        hkl,
        0
    )

    if not result:
        error = ctypes.get_last_error()

        raise OSError(
            f"ActivateKeyboardLayout failed: {error}"
        )

    return True