import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class StreamWishExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **_kwargs: Any) -> Dict[str, Any]:
        #
        # 1. Load embed page
        #
        response = await self._make_request(url)

        #
        # 2. Find iframe (if any)
        #
        iframe_match = re.search(
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            response.text,
            re.DOTALL
        )

        iframe_url = iframe_match.group(1) if iframe_match else url
        headers = {"Referer": url}

        #
        # 3. Load iframe page
        #
        iframe_response = await self._make_request(iframe_url, headers=headers)
        html = iframe_response.text

        #
        # 4. Extract m3u8 from plain JS (ONLY METHOD)
        #
        patterns = [
            # sources: [{ file: "https://...m3u8" }]
            r'sources:\s*\[\s*\{\s*file:\s*["\'](?P<url>https?://[^"\']+\.m3u8[^"\']*)',
            # links = { "hls2": "https://...m3u8" }
            r'links\s*=\s*\{[^}]+hls[24]"\s*:\s*"(?P<url>https?://[^"]+\.m3u8[^"]*)',
        ]

        final_url = None
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                final_url = match.group("url")
                break

        #
        # 5. Fail cleanly if nothing found
        #
        if not final_url:
            raise ExtractorError("StreamWish: Failed to extract m3u8")

        #
        # 6. Set referer
        #
        self.base_headers["Referer"] = url

        #
        # 7. Output
        #
        return {
            "destination_url": final_url,
            "request_headers": self.base_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }
