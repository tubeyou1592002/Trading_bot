import requests

from models.instrument import Instrument


BASE_URL = "https://cdn.tsetmc.com/api"


class TSETMC:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0"
        })

    def search(self, text: str):
        """جستجوی نمادها"""

        text = text.strip()

        if not text:
            return []

        url = f"{BASE_URL}/Instrument/GetInstrumentSearch/{text}"

        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()

        results = []

        for item in data.get("instrumentSearch", []):

            results.append({
                "symbol": item.get("lVal18AFC"),
                "name": item.get("lVal30"),
                "ins_code": item.get("insCode"),
                "flow": item.get("flow"),
                "market": item.get("flowTitle"),
            })

        return results

    def get_info(self, ins_code: str):
        """دریافت اطلاعات کامل نماد"""

        url = f"{BASE_URL}/Instrument/GetInstrumentInfo/{ins_code}"

        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        info = response.json()["instrumentInfo"]

        return Instrument(
            symbol=info.get("lVal18AFC"),
            name=info.get("lVal30"),
            ins_code=info.get("insCode"),
            instrument_id=info.get("instrumentID"),
            isin=info.get("cIsin"),
            market=info.get("flowTitle"),
            flow=info.get("flow"),
        )