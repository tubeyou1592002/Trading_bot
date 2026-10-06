"""
ui/strings.py — UI-9 Task 3: every user-facing string in ONE place, in Persian.

Why this module exists
----------------------
The User Application is Persian and right-to-left. Before this module the
same English sentence was duplicated across ``ui/order_configuration_page.py``,
``ui/schedule_settings.py``, ``ui/accounts_page.py`` and ``ui/main_window.py``,
and the tests had to hardcode those English literals. Centralising them here
means:

  * the UI and the tests read the SAME value, so localization can never drift
    out of sync with the assertions that check it,
  * adding a language later is one file, not a hunt through four modules.

Import contract (C6 / UI-3.1 ``test_14``)
-----------------------------------------
This module imports **nothing at all** — no PySide6, no ``ui.*``, no ``core``,
no ``brokers``, no ``market``, no ``main``. It is pure data plus the digit
formatter. That keeps it import-safe from any layer.

Digit policy (approved by the Product Owner)
--------------------------------------------
``format_technical`` keeps **LATIN** digits — used for the countdown, the
order-log send time and any other technical/timestamp value, where digit
precision and glyph recognition matter.

``format_persian_digits`` renders **PERSIAN** digits — used for money, price
and quantity, where readability for a Persian-speaking user matters.

Both go through this one module; ad-hoc ``str.translate`` calls scattered in
the pages are exactly what this policy forbids.
"""

__all__ = [
    # --- group / section titles ---
    "GROUP_ACTIVE_ACCOUNT",
    "GROUP_ORDER_CONFIGURATION",
    "GROUP_SYMBOL_INFORMATION",
    "GROUP_AMOUNTS",
    "GROUP_SCHEDULE",
    "GROUP_QUEUE_STATUS",
    "GROUP_ORDER_QUEUE",
    "GROUP_TEST_RESULTS",
    "GROUP_ORDER_LOG",
    "GROUP_DIAGNOSTIC",
    # --- order form ---
    "LABEL_SYMBOL",
    "LABEL_SIDE",
    "LABEL_PRICE",
    "LABEL_QUANTITY",
    "PLACEHOLDER_PRICE",
    "PLACEHOLDER_QUANTITY",
    "PLACEHOLDER_SYMBOL",
    "BUTTON_ADD_TO_QUEUE",
    "BUTTON_TEST",
    "BUTTON_TEST_ON",
    # --- symbol information ---
    "LABEL_NAME",
    "LABEL_STATUS",
    "LABEL_TRADING_STATE",
    # --- amounts ---
    "LABEL_BASE_AMOUNT",
    "LABEL_FEE",
    "LABEL_FINAL_AMOUNT",
    "VALUE_NOT_AVAILABLE",
    "VALUE_EMPTY_DASH",
    # --- queue ---
    "QUEUE_COUNT_LABEL",
    "QUEUE_COUNT_FORMAT",
    # --- schedule ---
    "LABEL_TIMEZONE",
    "LABEL_START_TIME",
    "LABEL_END_TIME",
    "LABEL_INTERVAL_SECONDS",
    "LABEL_DISPATCH_INTERVAL_MS",
    "LABEL_CLOCK",
    "LABEL_SYNC",
    "LABEL_STATE",
    "LABEL_COUNTDOWN",
    "LABEL_SUMMARY",
    "PLACEHOLDER_TIME_INPUT",
    "PLACEHOLDER_INTERVAL_INPUT",
    "PLACEHOLDER_DISPATCH_INTERVAL",
    "NOTE_TIMEZONE",
    "SUMMARY_WINDOW",
    "SUMMARY_INTERVAL",
    "SUMMARY_RUN_MOMENTS",
    "SUMMARY_STATE",
    "SUMMARY_SKIPPED",
    "SUMMARY_NEXT_MOMENTS",
    "SUMMARY_NEXT_MOMENTS_NONE",
    "SUMMARY_IMMEDIATE_START",
    "SUMMARY_CLOCK",
    "SYMBOL_STATUS_NOT_AVAILABLE_DISPLAY",
    "NO_ACTIVE_ACCOUNT",
    "RESULT_EMPTY_STATE",
    "DIAGNOSTIC_EMPTY_STATE",
    "DIAGNOSTIC_LATENCY_TOTAL_LABEL",
    "BUTTON_APPLY_SCHEDULE",
    "BUTTON_STOP_SCHEDULE",
    "BUTTON_REFRESH_CLOCK",
    "TOOLTIP_FORCE_SYNC",
    # --- schedule state ---
    "STATE_CONFIGURING",
    "STATE_WAITING",
    "STATE_COUNTING",
    "STATE_START_NOW",
    "STATE_STOPPED",
    "STATE_EXPIRED",
    # --- sync state ---
    "SYNC_IN_PROGRESS",
    "SYNC_NEVER",
    "SYNC_FAILED",
    "BUTTON_SYNC",
    "BUTTON_SYNC_BUSY",
    "BUTTON_SYNC_FAILED",
    # --- countdown ---
    "COUNTDOWN_UNAVAILABLE",
    "COUNTDOWN_NO_UPCOMING",
    "COUNTDOWN_STOPPED",
    # --- symbol search ---
    "SEARCH_SEARCHING",
    "SEARCH_NO_RESULTS",
    # --- queue status ---
    "QUEUE_STATUS_EMPTY",
    "QUEUE_STATUS_NO_ACCOUNT",
    "QUEUE_STATUS_NO_SYMBOL",
    "QUEUE_STATUS_INCOMPLETE",
    "QUEUE_STATUS_NO_IDENTITY",
    "QUEUE_STATUS_BROKER_STALE",
    "QUEUE_STATUS_QUEUED",
    # --- accounts page ---
    "GROUP_ADD_ACCOUNT",
    "GROUP_ACCOUNTS",
    "LABEL_ACCOUNT_ID",
    "LABEL_BROKER",
    "BUTTON_ADD",
    "BUTTON_SET_ACTIVE",
    "DIALOG_INVALID_ACCOUNT",
    "DIALOG_NO_SELECTION",
    "DIALOG_SELECT_ACCOUNT_FIRST",
    # --- order validation dialogs (removed from the path in UI-9.4; titles
    #     centralized here so UI-9.4 has one place to change) ---
    "DIALOG_INVALID_SIDE",
    "DIALOG_INVALID_PRICE",
    "DIALOG_INVALID_QUANTITY",
    # --- navigation: KEYS stay English (they are dict keys); DISPLAY is Persian ---
    "NAV_HOME",
    "NAV_ACCOUNTS",
    "NAV_ORDER_CONFIGURATION",
    "NAV_SETTINGS",
    "PLACEHOLDER_PAGE_BODY",
    "MODE_LABEL_PREFIX",
    "MODE_NORMAL",
    "MODE_DIAGNOSTIC",
    "WINDOW_TITLE",
    "BUTTON_DIAGNOSTIC_MODE",
    "TOOLTIP_DIAGNOSTIC_MODE",
    # --- digit policy ---
    "format_technical",
    "format_persian_digits",
    "format_grouped",
    "PERSIAN_DIGITS",
    "PERSIAN_THOUSANDS_SEPARATOR",
]

# ============================================================
# Digit policy — the ONE centralized formatter
# ============================================================

#: Unicode code points of the Persian (Extended Arabic-Indic) digits 0-9.
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

#: The Persian thousands separator, U+066C (not an ASCII comma).
PERSIAN_THOUSANDS_SEPARATOR = "٬"


def format_technical(value):
    """
    Render a technical/timestamp value, keeping **LATIN** digits.

    Used for the countdown, the order-log send time and any other precise
    technical value, where a monospace glyph run must stay scannable.
    Non-digit characters (separators, units, Persian letters) are preserved
    untouched, so an already-formatted value passes through unchanged.
    """
    return str(value)


def format_persian_digits(value, thousands_separator="٬"):
    """
    Render a money / price / quantity value using **PERSIAN** digits.

    Used for the base amount, the fee, the final amount, the price and the
    quantity — the values a user reads at a glance rather than measures.

    Only ASCII digits are converted. ``thousands_separator`` is retained for
    API symmetry with :func:`format_grouped`; the digit conversion itself does
    not depend on it.
    """
    text = str(value)
    out = []
    for character in text:
        if "0" <= character <= "9":
            out.append(PERSIAN_DIGITS[ord(character) - ord("0")])
        else:
            out.append(character)
    return "".join(out)


def format_grouped(value):
    """
    Format a numeric value as grouped money with **PERSIAN** digits.

    Grouping is applied to plain ASCII digits FIRST, and the ASCII separator
    it produces is then swapped for the Persian thousands separator U+066C
    during the digit pass. Doing it in this order keeps the grouping logic
    simple (Python's own ``{:,}``) while guaranteeing the rendered separator
    is the Persian one rather than an ASCII comma.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return format_persian_digits(value)
    if number != int(number):
        grouped = "{:,.2f}".format(number)
    else:
        grouped = "{:,}".format(int(number))
    grouped = grouped.replace(",", PERSIAN_THOUSANDS_SEPARATOR)
    return format_persian_digits(grouped)




# ============================================================
# Group and section titles
# ============================================================

GROUP_ACTIVE_ACCOUNT = "حساب فعال"
GROUP_ORDER_CONFIGURATION = "مشخصات سفارش"
GROUP_SYMBOL_INFORMATION = "اطلاعات نماد"
GROUP_AMOUNTS = "مبالغ"
GROUP_SCHEDULE = "زمان‌بندی"
GROUP_QUEUE_STATUS = "وضعیت صف"
GROUP_ORDER_QUEUE = "صف سفارش‌ها"
GROUP_TEST_RESULTS = "نتیجه اجرا"
GROUP_ORDER_LOG = "لاگ سفارش‌ها"
GROUP_DIAGNOSTIC = "عیب‌یابی - جزئیات اجرا"


# ============================================================
# Order form
# ============================================================

LABEL_SYMBOL = "نماد:"
LABEL_SIDE = "نوع معامله:"
LABEL_PRICE = "قیمت:"
LABEL_QUANTITY = "تعداد:"

PLACEHOLDER_SYMBOL = "مثلاً آگاه - تفکیک نام و نماد در مرحله بعدی انجام می‌شود"
PLACEHOLDER_PRICE = "ریال - عددی"
PLACEHOLDER_QUANTITY = "عددی"

BUTTON_ADD_TO_QUEUE = "افزودن به صف"
BUTTON_TEST = "تست"
BUTTON_TEST_ON = "تست (فعال)"


# ============================================================
# Symbol information and amounts
# ============================================================

LABEL_NAME = "نام:"
LABEL_STATUS = "وضعیت:"
LABEL_TRADING_STATE = "وضعیت معامله:"

LABEL_BASE_AMOUNT = "مبلغ پایه:"
LABEL_FEE = "کارمزد:"
LABEL_FINAL_AMOUNT = "مبلغ نهایی:"

VALUE_NOT_AVAILABLE = "در دسترس نیست"
VALUE_EMPTY_DASH = "-"

#: Same label with a live count. Persian digits, centralized formatter.
QUEUE_COUNT_FORMAT = "{count} سفارش در صف"
#: Built from QUEUE_COUNT_FORMAT below so the digit policy has ONE home.
QUEUE_COUNT_LABEL = QUEUE_COUNT_FORMAT.format(
    count=format_persian_digits(0)
)


# ============================================================
# Schedule
# ============================================================

LABEL_TIMEZONE = "منطقه زمانی:"
LABEL_START_TIME = "زمان شروع:"
LABEL_END_TIME = "زمان پایان:"
LABEL_INTERVAL_SECONDS = "فاصله (ثانیه):"
LABEL_DISPATCH_INTERVAL_MS = "فاصله ارسال (میلی‌ثانیه):"
LABEL_CLOCK = "ساعت:"
LABEL_SYNC = "همگام‌سازی:"
LABEL_STATE = "وضعیت:"
LABEL_COUNTDOWN = "شمارش معکوس:"
LABEL_SUMMARY = "خلاصه:"

PLACEHOLDER_TIME_INPUT = "تهران HH:MM:SS"
PLACEHOLDER_INTERVAL_INPUT = "فاصله بین اجراها به ثانیه"
PLACEHOLDER_DISPATCH_INTERVAL = "میلی‌ثانیه بین ارسال‌ها"

# The IANA identifier is a *technical* token, not prose: it stays Latin so the
# timezone stays unambiguous and machine-matchable (same rule as timestamps).
NOTE_TIMEZONE = "به وقت تهران (Asia/Tehran, UTC+03:30)"

# --- schedule summary lines (see schedule_settings.describe_summary) ---------
# Clock/moment times inside these lines are technical and stay Latin; the
# counts are quantities and go through format_persian_digits.
SUMMARY_WINDOW = "بازه: {start} - {end} ({timezone})"
SUMMARY_INTERVAL = "فاصله: هر {interval} ثانیه"
SUMMARY_RUN_MOMENTS = "تعداد اجراها در بازه: {count}"
SUMMARY_STATE = "وضعیت: {state}"
SUMMARY_SKIPPED = "اجراهای از دست رفته: {count} (تکرار نمی‌شوند)"
SUMMARY_NEXT_MOMENTS = "اجراهای بعدی ({count} باقی‌مانده): {times}"
SUMMARY_NEXT_MOMENTS_NONE = "اجراهای بعدی: وجود ندارد"
SUMMARY_IMMEDIATE_START = "شروع فوری: یک‌بار، هم‌اکنون"
SUMMARY_CLOCK = "ساعت: {clock}"

# --- shared display-only states -------------------------------------------
# The *token* SYMBOL_STATUS_NOT_AVAILABLE ("Not available") stays English in
# ui.order_config_state because it is a machine-checked state value; only its
# rendering is Persian.
SYMBOL_STATUS_NOT_AVAILABLE_DISPLAY = "ناموجود"

NO_ACTIVE_ACCOUNT = "حساب فعالی وجود ندارد - یکی را در صفحهٔ حساب‌ها انتخاب کنید"

# Empty states of the Test Results and Diagnostic areas before the first run.
RESULT_EMPTY_STATE = (
    "هنوز نتیجه‌ای ثبت نشده است - ابتدا آزمایش را اجرا کنید."
)
DIAGNOSTIC_EMPTY_STATE = "هنوز حالت آزمایشی اجرا نشده است."
DIAGNOSTIC_LATENCY_TOTAL_LABEL = "زمان کل ارسال: "

BUTTON_APPLY_SCHEDULE = "اعمال زمان‌بندی"
BUTTON_STOP_SCHEDULE = "توقف زمان‌بندی"
BUTTON_REFRESH_CLOCK = "به‌روزرسانی ساعت"
TOOLTIP_FORCE_SYNC = "همگام‌سازی فوری ساعت بازار"


# ============================================================
# Schedule lifecycle state
# ============================================================

STATE_CONFIGURING = "در حال پیکربندی"
STATE_WAITING = "در انتظار زمان شروع"
STATE_COUNTING = "در حال شمارش معکوس"
STATE_START_NOW = "زمان شروع رسید - یک‌بار فوراً اجرا می‌شود"
STATE_STOPPED = "زمان‌بندی متوقف شد - دوباره در حال پیکربندی"
STATE_EXPIRED = "زمان‌بندی منقضی شد - هیچ ارسالی انجام نمی‌شود"


# ============================================================
# Clock sync
# ============================================================

SYNC_IN_PROGRESS = "همگام‌سازی در حال انجام - در انتظار نتیجه…"
SYNC_NEVER = (
    "هنوز همگام‌سازی ساعت بازار انجام نشده - ابتدا «همگام‌سازی ساعت» "
    "را بزنید (در حال حاضر ساعت سیستم استفاده می‌شود)"
)
SYNC_FAILED = "آخرین همگام‌سازی ناموفق بود - زمان بازار در دسترس نیست، ساعت سیستم استفاده می‌شود"

BUTTON_SYNC = "همگام‌سازی ساعت"
BUTTON_SYNC_BUSY = "در حال همگام‌سازی…"
BUTTON_SYNC_FAILED = "ناموفق - دوباره تلاش کنید"


# ============================================================
# Countdown
# ============================================================

COUNTDOWN_UNAVAILABLE = "-"
COUNTDOWN_NO_UPCOMING = "اجرای بعدی وجود ندارد - زمان‌بندی منقضی شد"
COUNTDOWN_STOPPED = "زمان‌بندی متوقف شد - شمارش معکوس لغو شد"


# ============================================================
# Symbol search
# ============================================================

SEARCH_SEARCHING = "در حال جست‌وجو…"
SEARCH_NO_RESULTS = "نمادی یافت نشد"


# ============================================================
# Queue status
# ============================================================

QUEUE_STATUS_EMPTY = "هنوز سفارشی در صف نیست - فرم را تنظیم کنید و «افزودن به صف» را بزنید"
QUEUE_STATUS_NO_ACCOUNT = "امکان افزودن به صف نیست: حساب فعالی وجود ندارد - در صفحه حساب‌ها یکی انتخاب کنید"
QUEUE_STATUS_NO_SYMBOL = "امکان افزودن به صف نیست: نمادی انتخاب نشده است"
QUEUE_STATUS_INCOMPLETE = "امکان افزودن به صف نیست: نوع معامله، قیمت و تعداد را کامل کنید"
QUEUE_STATUS_NO_IDENTITY = "امکان افزودن به صف نیست: شناسهٔ سفارش نماد هنوز تفکیک نشده - نماد را دوباره انتخاب کنید"
QUEUE_STATUS_BROKER_STALE = "امکان افزودن به صف نیست: شناسهٔ سفارش به کارگزار دیگری تعلق دارد - نماد را دوباره انتخاب کنید"
QUEUE_STATUS_QUEUED = "سفارش در صف قرار گرفت"


# ============================================================
# Test (dry-run) action outcomes
# ============================================================

TEST_SKIPPED_NO_ORDERS = "اجرای تست انجام نشد: سفارشی در صف نیست"
TEST_SKIPPED_NO_ACCOUNT = "اجرای تست انجام نشد: حساب فعالی وجود ندارد (fail-closed)"
TEST_SKIPPED_ACCOUNT_MISMATCH = "اجرای تست انجام نشد: حساب فعال با نماد انتخاب‌شده هم‌خوانی ندارد"
TEST_ISSUE_FAILED = "امکان اجرای تست نبود: {exc}"
TEST_ISSUED = "اجرای تست ثبت شد (dry-run): شناسهٔ اجرا {execution_id}"


# ============================================================
# Diagnostic section line prefixes
# ============================================================

DIAGNOSTIC_ENTRY_PREFIX = "سفارش #{position}: "
DIAGNOSTIC_VERDICT_PREFIX = "نتیجهٔ اجرا: "
DIAGNOSTIC_TRACE_LABEL = "شناسهٔ رهگیری: "
DIAGNOSTIC_STAGE_PREFIX = "سفارش {order} - مرحله {stage}: "
DIAGNOSTIC_BROKER_PREFIX = "سفارش {order} - Broker/API {operation} #{call_number} (رفتوبرگشت): "
DIAGNOSTIC_BROKER_NONE = (
    "سفارش {order} - Broker/API: فراخوانی ثبت‌شده‌ای نیست"
)

LABEL_SYMBOL_STATUS_PREFIX = "وضعیت: "


# ============================================================
# Clock sync line (UI-7 Task 1)
# ============================================================

SYNC_STALE = (
    "آخرین همگام‌سازی {age} ثانیه پیش انجام شد و از سقف {limit} ثانیهٔ زمان‌بندی "
    "قدیمی‌تر است - دکمهٔ «{button}» را دوباره بزنید (ساعت سیستم در حال استفاده است)"
)
SYNC_OK_PREFIX = "همگام‌سازی {age} ثانیه پیش - منبع {source}، "
SYNC_OK_OFFSET = "آفست {offset}، "
SYNC_OK_UNCERTAINTY = "عدم‌قطعیت {uncertainty}، "
SYNC_OK_FAILED_SUFFIX = " (آخرین تلاش ناموفق بود)"

SCHEDULE_REJECTED = "زمان‌بندی رد شد - {reason}"
COUNTDOWN_NEXT_RUN = "اجرای بعدی در: {clock} (ساعت {tehran} تهران)"


# ============================================================
# Accounts page
# ============================================================

GROUP_ADD_ACCOUNT = "افزودن حساب"
GROUP_ACCOUNTS = "حساب‌ها"

LABEL_ACCOUNT_ID = "شناسه حساب:"
LABEL_BROKER = "کارگزار:"

BUTTON_ADD = "افزودن"
BUTTON_SET_ACTIVE = "فعال‌سازی"

PLACEHOLDER_ACCOUNT_ID = "مثلاً ACC-001 - شناسهٔ صریح حساب"

TABLE_HEADER_ACCOUNT_ID = "شناسه حساب"
TABLE_HEADER_BROKER = "کارگزار"
TABLE_HEADER_ACTIVE = "فعال"

DIALOG_INVALID_ACCOUNT = "حساب نامعتبر"
DIALOG_NO_SELECTION = "بدون انتخاب"
DIALOG_SELECT_ACCOUNT_FIRST = "ابتدا یک حساب را از فهرست انتخاب کنید."


# ============================================================
# Order validation dialog titles
# (UI-9.4 replaces these modals with inline errors; the values live here
#  so that task has a single place to update.)
# ============================================================

DIALOG_INVALID_SIDE = "نوع معامله نامعتبر"
DIALOG_INVALID_PRICE = "قیمت نامعتبر"
DIALOG_INVALID_QUANTITY = "تعداد نامعتبر"


# ============================================================
# Navigation
#
# IMPORTANT (Step 3 warning): the four NAV_* values below are also the PAGE
# KEYS used by MainWindow.pages, NAVIGATION_ITEMS and PLACEHOLDER_ITEMS.
# Tests look pages up by those keys, so the KEYS STAY ENGLISH. Only the text
# handed to the nav buttons and to the placeholder label is Persian.
# ============================================================

NAV_HOME = "Home"
NAV_ACCOUNTS = "Accounts"
NAV_ORDER_CONFIGURATION = "Order Configuration"
NAV_SETTINGS = "Settings"

#: Display text for the nav buttons / placeholder label, keyed by page key.
NAV_DISPLAY = {
    NAV_HOME: "خانه",
    NAV_ACCOUNTS: "حساب‌ها",
    NAV_ORDER_CONFIGURATION: "مشخصات سفارش",
    NAV_SETTINGS: "تنظیمات",
}


def nav_display(page_key):
    """Return the Persian label for a navigation page key.

    Falls back to the key itself so an unknown key can never raise during
    rendering — navigation must never break because of a missing label.
    """
    return NAV_DISPLAY.get(page_key, page_key)


PLACEHOLDER_PAGE_BODY = "صفحهٔ خانه هنوز پیاده‌سازی نشده است."

MODE_LABEL_PREFIX = "حالت:"
MODE_NORMAL = "عادی"
MODE_DIAGNOSTIC = "عیب‌یابی"

WINDOW_TITLE = "ربات معاملاتی - برنامه کاربر"

BUTTON_DIAGNOSTIC_MODE = "حالت عیب‌یابی"
TOOLTIP_DIAGNOSTIC_MODE = (
    "جابه‌جایی بین حالت عادی و حالت عیب‌یابی: در حالت عیب‌یابی "
    "ممکن است جزئیات فنی اجرای سفارش نمایش داده شود."
)

