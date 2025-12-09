import re
import json
from typing import Dict, Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class F16PxExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "hls_manifest_proxy"

    # --- base64url decode (ResolveURL ft) ---
    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        value = value.replace("-", "+").replace("_", "/")
        while len(value) % 4:
            value += "="
        return __import__("base64").b64decode(value)

    # --- key join (ResolveURL xn) ---
    def _join_key_parts(self, parts):
        return b"".join(self._b64url_decode(p) for p in parts)

    async def extract(self, url: str) -> Dict[str, Any]:
        parsed = urlparse(url)
        if not parsed.hostname or not parsed.hostname.endswith(
            ("f16px.com", "bysesayeveum.com")
        ):
            raise ExtractorError("F16PX: Invalid domain")

        # extract media id
        match = re.search(r"/e/([A-Za-z0-9]+)", parsed.path)
        if not match:
            raise ExtractorError("F16PX: Invalid embed URL")

        media_id = match.group(1)
        api_url = f"https://{parsed.hostname}/api/videos/{media_id}/embed/playback"

        headers = self.base_headers.copy()
        headers["referer"] = f"https://{parsed.hostname}/"

        # --- Fetch playback JSON ---
        resp = await self._make_request(api_url, headers=headers)

        try:
            data = resp.json()
        except Exception:
            raise ExtractorError("F16PX: Invalid JSON response")

        # --- Case 1: Plain sources ---
        if "sources" in data:
            src = data["sources"][0]["url"]
            return {
                "destination_url": src,
                "request_headers": headers,
                "mediaflow_endpoint": self.mediaflow_endpoint,
            }

        # --- Case 2: Encrypted playback ---
        pb = data.get("playback")
        if not pb:
            raise ExtractorError("F16PX: No playback data")

        try:
            iv = self._b64url_decode(pb["iv"])
            key = self._join_key_parts(pb["key_parts"])
            payload = self._b64url_decode(pb["payload"])

            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(iv, payload, None)
            decrypted_json = json.loads(decrypted.decode("utf-8"))

        except Exception as e:
            raise ExtractorError(f"F16PX: Decryption failed ({e})")

        sources = decrypted_json.get("sources")
        if not sources:
            raise ExtractorError("F16PX: No sources after decryption")

        best = sources[0]["url"]

        return {
            "destination_url": best,
            "request_headers": headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }
