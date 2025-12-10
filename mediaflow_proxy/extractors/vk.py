import json
import re
from typing import Dict, Any
from urllib.parse import urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):
    """
    VK MediaFlow extractor (CORRECT VERSION)
    - al_video.php → extract HLS master
    - MediaFlow proxies playlist + segments
    """

    mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)

        ajax_url = self._build_ajax_url(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": "remixlang=0",
        }

        response = await self._make_request(
            ajax_url,
            method="POST",
            data=self._build_ajax_data(embed_url),
            headers=headers,
        )

        text = response.text.lstrip("<!--")

        try:
            js = json.loads(text)
        except Exception:
            raise ExtractorError("VK: invalid JSON")

        hls_url = self._extract_hls(js)
        if not hls_url:
            raise ExtractorError("VK: HLS not found")

        # ✅ IMPORTANT: Return URL ONLY
        return {
            "destination_url": hls_url,
            "request_headers": {
                "Referer": "https://vkvideo.ru/",
                "User-Agent": UA,
            },
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    # --------------------------------------------------

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            raise ExtractorError("VK: invalid URL")

        oid, vid = m.groups()
        return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = urlparse(embed_url).netloc
        return f"https://{host}/al_video.php"

    def _build_ajax_data(self, embed_url: str) -> Dict[str, str]:
        qs = dict(
            part.split("=", 1)
            for part in embed_url.split("?", 1)[1].split("&")
        )
        return {
            "act": "show",
            "al": "1",
            "video": f"{qs['oid']}_{qs['id']}",
        }

    def _extract_hls(self, data: Any) -> str | None:
        for item in data.get("payload", []):
            if isinstance(item, list):
                for block in item:
                    if isinstance(block, dict) and block.get("player"):
                        params = block["player"]["params"][0]
                        return (
                            params.get("hls")
                            or params.get("hls_ondemand")
                            or params.get("hls_live")
                        )
        return None
