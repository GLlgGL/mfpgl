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
    mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        embed_url = self._normalize(url)

        # --- 1️⃣ Call VK API ---
        ajax_url = self._build_ajax_url(embed_url)
        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
        }

        response = await self._make_request(
            ajax_url,
            method="POST",
            data=self._build_ajax_data(embed_url),
            headers=headers,
        )

        text = response.text.lstrip("<!--")

        try:
            json_data = json.loads(text)
        except Exception:
            raise ExtractorError("VK: invalid JSON payload")

        playlist_url = self._extract_stream(json_data)
        if not playlist_url:
            raise ExtractorError("VK: no playable HLS URL found")

        # --- 2️⃣ Fetch playlist ---
        playlist_resp = await self._make_request(
            playlist_url,
            method="GET",
            headers={"Referer": "https://vkvideo.ru/"},
        )

        rewritten_playlist = self._rewrite_playlist(
            playlist_resp.text, playlist_url
        )

        # --- 3️⃣ Return rewritten playlist ---
        return {
            "destination_url": rewritten_playlist,
            "request_headers": {
                "Referer": "https://vkvideo.ru/",
                "User-Agent": UA,
            },
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _rewrite_playlist(self, playlist: str, master_url: str) -> str:
        """Rewrite relative HLS URLs to absolute (VLC/Stremio fix)."""
        base = urlparse(master_url).scheme + "://" + urlparse(master_url).netloc
        out = []

        for line in playlist.splitlines():
            if line.startswith("/"):
                out.append(base + line)
            else:
                out.append(line)

        return "\n".join(out)

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(\d+)_(\d+)", url)
        if not m:
            raise ExtractorError("VK: invalid URL format")

        oid, vid = m.group(1), m.group(2)
        return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
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

    def _extract_stream(self, json_data: Any) -> str | None:
        for item in json_data.get("payload", []):
            if isinstance(item, list):
                for block in item:
                    if isinstance(block, dict) and block.get("player"):
                        params = block["player"]["params"][0]
                        return (
                            params.get("hls")
                            or params.get("hls_ondemand")
                            or params.get("hls_live")
                            or params.get("url1080")
                            or params.get("url720")
                            or params.get("url480")
                            or params.get("url360")
                        )
        return None
