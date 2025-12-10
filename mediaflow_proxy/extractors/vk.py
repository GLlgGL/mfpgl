import json
import re
from typing import Dict, Any
from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36"
)

class VKExtractor(BaseExtractor):
    mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)

        ajax_url = self._ajax_url(embed_url)
        data = self._ajax_data(embed_url)

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
            data=data,
            headers=headers,
        )

        text = response.text.lstrip("<!--")

        try:
            js = json.loads(text)
        except Exception:
            raise ExtractorError("VK: invalid JSON")

        hls = self._extract_hls(js)
        if not hls:
            raise ExtractorError("VK: HLS not found")

        # ✅ RETURN RAW PLAYLIST URL ONLY
        return {
            "destination_url": hls,
            "request_headers": {
                "User-Agent": UA,
                "Referer": "https://vkvideo.ru/",
            },
            "mediaflow_endpoint": "hls_manifest_proxy",
        }

    # ---------------- helpers ----------------

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url
        m = re.search(r"video(\d+)_(\d+)", url)
        if not m:
            raise ExtractorError("Invalid VK URL")
        oid, vid = m.group(1), m.group(2)
        return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

    def _ajax_url(self, embed: str) -> str:
        host = re.search(r"https?://([^/]+)", embed).group(1)
        return f"https://{host}/al_video.php?act=show"

    def _ajax_data(self, embed: str) -> Dict[str, str]:
        qs = dict(p.split("=") for p in embed.split("?", 1)[1].split("&"))
        return {
            "act": "show",
            "al": "1",
            "video": f"{qs['oid']}_{qs['id']}",
        }

    def _extract_hls(self, js: Any) -> str | None:
        payload = next((x for x in js.get("payload", []) if isinstance(x, list)), [])
        for block in payload:
            if isinstance(block, dict) and block.get("player"):
                params = block["player"]["params"][0]
                return params.get("hls") or params.get("hls_ondemand")
        return None
