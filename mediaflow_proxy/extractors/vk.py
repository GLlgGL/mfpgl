import json
import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)
        ajax_url = self._build_ajax_url(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
        }

        data = self._build_ajax_data(embed_url)

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
            raise ExtractorError("VK: invalid JSON payload")

        stream, kind = self._extract_stream(js)
        if not stream:
            raise ExtractorError("VK: no playable stream found")

        if kind == "mpd":
            endpoint = "mpd_manifest_proxy"
        elif kind == "hls":
            endpoint = "hls_manifest_proxy"
        else:
            endpoint = "proxy_stream_endpoint"

        return {
            "destination_url": stream,
            "request_headers": headers,
            "mediaflow_endpoint": endpoint,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            return url

        oid, vid = m.group(1), m.group(2)
        return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url: str):
        qs = re.search(r"\?(.*)", embed_url)
        parts = dict(x.split("=") for x in qs.group(1).split("&")) if qs else {}
        return {
            "act": "show",
            "al": "1",
            "video": f"{parts.get('oid')}_{parts.get('id')}",
        }

    # ------------------------------------------------------------------
    # STREAM SELECTION (DASH FIRST)
    # ------------------------------------------------------------------

    def _extract_stream(self, js: Any) -> tuple[str | None, str | None]:
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
            return None, None

        # ✅ 1. DASH (MPD) — ALWAYS FIRST
        if params.get("dash"):
            return params["dash"], "mpd"

        # ✅ 2. HLS fallback
        if params.get("hls"):
            return params["hls"], "hls"

        # ✅ 3. MP4 LAST (avoid when possible)
        mp4 = (
            params.get("url1080")
            or params.get("url720")
            or params.get("url480")
            or params.get("url360")
        )

        if mp4:
            return mp4, "mp4"

        return None, None
