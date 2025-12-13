import re
from typing import Dict, Any
from urllib.parse import urljoin, urlparse

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class StreamWishExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        #
        # 0. Get external referer (ResolveURL $$ equivalent)
        #
        page_referer = kwargs.get("h_referer")

        #
        # 1. Load embed page
        #
        response = await self._make_request(url)

        #
        # 2. Find iframe
        #
        iframe_match = re.search(
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            response.text,
            re.DOTALL
        )

        iframe_url = iframe_match.group(1) if iframe_match else url

        #
        # 3. Decide the REAL referer
        #
        if page_referer:
            referer = urljoin(page_referer, "/")
        else:
            referer = iframe_url.split("/e/")[0] + "/"

        headers = {"Referer": referer}

        #
        # 4. Load iframe page
        #
        iframe_response = await self._make_request(iframe_url, headers=headers)
        html = iframe_response.text

        #
        # 5. Extract m3u8
        #
        patterns = [
            r'sources:\s*\[\s*\{\s*file:\s*["\'](?P<url>https?://[^"\']+)',
            r'sources:\s*\[\s*\{\s*file:\s*["\'](?P<url>/stream/[^"\']+)',
            r'player\.src\(\s*["\'](?P<url>https?://[^"\']+)',
            r'file:\s*["\'](?P<url>https?://[^"\']+)',
        ]

        final_url = None
        for pattern in patterns:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                final_url = m.group("url")
                break

        if final_url and final_url.startswith("/"):
            final_url = urljoin(iframe_url, final_url)

        if not final_url or "m3u8" not in final_url:
            raise ExtractorError("StreamWish: Failed to extract m3u8")

        #
        # 6. Set FINAL headers (this is what MediaFlow outputs)
        #
        origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"

        self.base_headers.update({
            "Referer": referer,
            "Origin": origin,
        })

        #
        # 7. Output
        #
        return {
            "destination_url": final_url,
            "request_headers": self.base_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }
