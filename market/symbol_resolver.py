from market.tsetmc import TSETMC


class SymbolResolver:

    def __init__(self):
        self.tsetmc = TSETMC()

    @staticmethod
    def normalize(text: str) -> str:
        text = text.strip()

        # یکسان‌سازی حروف فارسی و عربی
        text = text.replace("ي", "ی")
        text = text.replace("ى", "ی")
        text = text.replace("ك", "ک")

        return text

    def search(self, text: str):
        text = self.normalize(text)

        if not text:
            return []

        results = self.tsetmc.search(text)

        # نتیجه دقیق‌تر اول نمایش داده شود
        results.sort(
            key=lambda x: (
                x.get("symbol") != text,
                x.get("symbol") or ""
            )
        )

        return results

    def resolve(self, result):
        """
        دریافت اطلاعات کامل نماد
        """

        ins_code = result["ins_code"]

        if not isinstance(ins_code, str) or not ins_code.strip().isdigit():
            raise ValueError("ins_code must be a numeric TSETMC identifier")

        instrument = self.tsetmc.get_info(ins_code)

        return instrument

    def get_price_limits(self, ins_code):
        """Return the TSETMC daily allowed price range for an InsCode."""
        return self.tsetmc.get_price_limits(ins_code)
