import logging
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


def parse_hls_playlist(
    playlist_content: str,
    base_url: Optional[str] = None
) -> List[Dict[str, Any]]:
    streams = []
    lines = playlist_content.strip().splitlines()

    if base_url:
        parsed = urlparse(base_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}/"

    stream_inf_pattern = re.compile(r'#EXT-X-STREAM-INF:(.*)')

    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue

        stream_info: Dict[str, Any] = {}
        match = stream_inf_pattern.match(line)
        if not match:
            continue

        attributes = re.findall(
            r'([A-Z-]+)=("([^"]+)"|([^,]+))',
            match.group(1),
        )

        for key, _, quoted, plain in attributes:
            value = quoted if quoted else plain
            if key == "RESOLUTION":
                try:
                    w, h = map(int, value.split("x"))
                    stream_info["resolution"] = (w, h)
                except ValueError:
                    stream_info["resolution"] = (0, 0)
            else:
                stream_info[key.lower().replace("-", "_")] = value

        # Next line = stream URL
        if i + 1 < len(lines):
            raw_url = lines[i + 1].strip()
            if raw_url.startswith("#"):
                continue

            if base_url:
                stream_info["url"] = urljoin(base_url, raw_url)
            else:
                stream_info["url"] = raw_url

            streams.append(stream_info)

    return streams
