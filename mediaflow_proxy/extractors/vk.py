import json
import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = "User-Agent: Mozilla/5.0"


class VKExtractor(BaseExtractor):
    """
    MediaFlow VK extractor
    - Matches curl + ResolveURL behavior
    - HLS ONLY
    """

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)
        ajax_url = self._build_ajax_url(embed_url)
        ajax_data = self._build_ajax_data(embed_url)

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
            data=ajax_data,
            headers=headers,
        )

        text = response.text
        if text.startswith("<!--"):
            text = text[4:]

        try:
            js = json.loads(text)
        except Exception:
            raise ExtractorError("VK: invalid JSON payload")

        hls_url = self._extract_hls(js)

        if not hls_url:
            raise ExtractorError("VK: HLS stream not found")

        return {
            "destination_url": hls_url,
            "request_headers": {
                "Referer": "https://vkvideo.ru/",
            },
            "mediaflow_endpoint": "hls_manifest_proxy",
        }

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            raise ExtractorError("VK: invalid URL format")

        oid, vid = m.group(1), m.group(2)
        return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        # ✅ EXACT match with curl / ResolveURL
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url: str) -> Dict[str, str]:
        qs = dict(
            item.split("=")
            for item in embed_url.split("?", 1)[1].split("&")
        )
        return {
            "act": "show",
            "al": "1",
            "video": f"{qs.get('oid')}_{qs.get('id')}",
        }

    # ------------------------------------------------------------
    # Extract HLS EXACTLY like ResolveURL
    # ------------------------------------------------------------

    def _extract_hls(self, js: Any) -> str | None:
        payload = []
        for item in js.get("payload", []):
            if isinstance(item, list):
                payload = item

        params = None
        for block in payload:
            if isinstance(block, dict) and block.get("player"):
                p = block["player"].get("params")
                if isinstance(p, list) and p:
                    params = p[0]

        if not params:
            return None

        # ✅ EXACT fallback order
        return (
            params.get("hls")
            or params.get("hls_ondemand")
            or params.get("hls_live")
        )
