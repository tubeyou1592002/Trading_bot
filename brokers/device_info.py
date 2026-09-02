import base64
import json
import platform
import re
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class DeviceInfoProvider:
    """
    تأمین کننده deviceInfo برای احراز هویت آگاه.
    """

    def get(self) -> dict:
        raise NotImplementedError(
            "deviceInfo provider هنوز پیاده‌سازی نشده است."
        )


class ExternalDeviceInfoProvider(DeviceInfoProvider):
    """
    تولید deviceInfo بر اساس الگوریتم مشاهده‌شده در JavaScript آگاه.
    """

    IV = "wR0R9+8O6bLc5Ix8"

    RSA_PUBLIC_KEY_B64 = """
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5qTDw9veXFdfThf3Rbae
fQHQKh3kT+bJxGpG+EH/qebW+EugLhDPNdWql2B0odSy0fyofdQutiLOV9Upc4K/
K99lmMLJEKY4gGr8rYOkYSgMUsabnJV6+lvSDHZ1ztv0rmq6H8wkNiqo36fYCtS6
TOJrNodPu60tQT81/sDsRx3xvEvbuvMJFBe4PVN2KnV8TrvkQciLbVVO4FOXsOe8
XA5yu4kST95pbNbeYT+Ltf1Oi9H1e87RNBKnpeibmjToyZvSGxmcwM0/Fe3/cBFq
qefnY9XzAAoAzvIdPpsEGkaf+3nBJfaL/0e8cJPi1IvJmjMJuDHTF+S/+Tuc0Jd5
qQIDAQAB
""".strip()

    def __init__(
        self,
        storage_file="client_id.txt",
        client_id=None,
    ):
        self.storage_file = Path(storage_file)
        self.client_id = client_id

    # =================================================
    # Client ID
    # =================================================

    def get_client_id(self) -> str:
        """
        اگر client_id به صورت مستقیم داده شده باشد، همان استفاده می‌شود.
        در غیر این صورت از client_id.txt خوانده می‌شود.
        اگر فایل وجود نداشته باشد، یک شناسه جدید ساخته می‌شود.
        """

        if self.client_id:
            return self.client_id

        if self.storage_file.exists():
            client_id = self.storage_file.read_text(
                encoding="utf-8"
            ).strip()

            if client_id:
                return client_id

        client_id = str(uuid.uuid4())

        self.storage_file.write_text(
            client_id,
            encoding="utf-8"
        )

        return client_id

    # =================================================
    # Client Information
    # =================================================

    def get_client_info(self) -> dict:
        """
        بازسازی getClientInfo() مطابق منطق JavaScript آگاه.
        """

        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        )

        # ---------------------------------------------
        # getDeviceModel()
        # ---------------------------------------------

        if "iPhone" in user_agent:
            device_model = "iPhone"

        elif "iPad" in user_agent:
            device_model = "iPad"

        else:
            android_match = re.search(
                r"Android.*;\s([^)]+)\)",
                user_agent
            )

            if android_match and android_match.group(1):
                device_model = android_match.group(1).strip()

            elif "Chrome" in user_agent:
                device_model = "Chrome"

            elif "Firefox" in user_agent:
                device_model = "Firefox"

            elif (
                "Safari" in user_agent
                and "Chrome" not in user_agent
            ):
                device_model = "Safari"

            elif "Edg" in user_agent:
                device_model = "Edge"

            else:
                device_model = "Unknown"

        # ---------------------------------------------
        # detectOS()
        # ---------------------------------------------

        ua_lower = user_agent.lower()

        if "windows phone" in ua_lower:
            os_name = "Windows Phone"

        elif "win" in ua_lower:
            os_name = "Windows"

        elif (
            "mac" in ua_lower
            and "iphone" not in ua_lower
            and "ipad" not in ua_lower
        ):
            os_name = "macOS"

        elif "android" in ua_lower:
            os_name = "Android"

        elif "linux" in ua_lower:
            os_name = "Linux"

        elif any(
            value in ua_lower
            for value in ("iphone", "ipad", "ipod")
        ):
            os_name = "iOS"

        else:
            os_name = "Unknown"

        # ---------------------------------------------
        # detectOSVersion()
        # ---------------------------------------------

        version_match = re.search(
            r"(Windows NT|Android|CPU (iPhone )?OS|Mac OS X|Linux)"
            r"[\s_/]?(\d+([._]\d+)*)",
            user_agent,
            re.IGNORECASE,
        )

        if version_match:
            os_version = version_match.group(3).replace(
                "_",
                "."
            )
        else:
            os_version = "unknown"

        # ---------------------------------------------
        # detectPlatform()
        # ---------------------------------------------

        platform_name = "web"

        # ---------------------------------------------
        # Final clientInfo
        # ---------------------------------------------

        return {
            "clientId": self.get_client_id(),
            "deviceModel": device_model,
            "osName": os_name,
            "osVersion": os_version,
            "appVersion": "3.1.1",
            "platform": platform_name,
        }

    # =================================================
    # AES
    # =================================================

    @staticmethod
    def _pkcs7_pad(
        data: bytes,
        block_size: int = 16,
    ) -> bytes:

        padding_length = block_size - (
            len(data) % block_size
        )

        return data + bytes(
            [padding_length] * padding_length
        )

    def encrypt_with_random_aes_key(
        self,
        plaintext: str,
    ):
        """
        معادل encryptWithRandomAesKey() در JavaScript آگاه.
        """

        aes_key = os_random_bytes(32)

        plaintext_bytes = plaintext.encode(
            "utf-8"
        )

        padded = self._pkcs7_pad(
            plaintext_bytes,
            16,
        )

        iv = self.IV.encode("utf-8")

        if len(iv) != 16:
            raise RuntimeError(
                "IV باید دقیقاً 16 بایت باشد."
            )

        cipher = Cipher(
            algorithms.AES(aes_key),
            modes.CBC(iv),
        )

        encryptor = cipher.encryptor()

        encrypted_bytes = (
            encryptor.update(padded)
            + encryptor.finalize()
        )

        encrypted_data = base64.b64encode(
            encrypted_bytes
        ).decode("ascii")

        aes_key_base64 = base64.b64encode(
            aes_key
        ).decode("ascii")

        return {
            "encryptedData": encrypted_data,
            "aesKey": aes_key_base64,
            "iv": self.IV,
        }

    # =================================================
    # RSA
    # =================================================

    def encrypt_with_rsa(
        self,
        plaintext: str,
    ) -> str:
        """
        معادل encryptWithRsa() در JavaScript آگاه.
        """

        public_key_der = base64.b64decode(
            self.RSA_PUBLIC_KEY_B64
        )

        public_key = serialization.load_der_public_key(
            public_key_der
        )

        encrypted = public_key.encrypt(
            plaintext.encode("utf-8"),
            padding.PKCS1v15(),
        )

        return base64.b64encode(
            encrypted
        ).decode("ascii")

    # =================================================
    # Device Info
    # =================================================

    def get(self) -> dict:
        """
        ساخت deviceInfo نهایی.
        """

        client_info = self.get_client_info()

        client_info_json = json.dumps(
            client_info,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        encrypted = self.encrypt_with_random_aes_key(
            client_info_json
        )

        encrypted_key = self.encrypt_with_rsa(
            encrypted["aesKey"]
        )

        return {
            "key": encrypted_key,
            "data": encrypted["encryptedData"],
            "nonce": encrypted["iv"],
        }


def os_random_bytes(length: int) -> bytes:
    """
    تولید بایت‌های تصادفی امن برای AES key.
    """

    import os

    return os.urandom(length)