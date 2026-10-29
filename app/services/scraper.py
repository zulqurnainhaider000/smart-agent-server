"""
app/services/scraper.py
-----------------------
Advanced safe web scraping and content extraction service.
Modeled after Meta's Muse document perception layer.

Fetches target web pages, guards against SSRF (Server-Side Request Forgery),
enforces strict size and timeout caps, and extracts clean, readable text.
"""

import ipaddress
import logging
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# Maximum content size to download (512 KB to avoid memory bloat / zip bombs)
MAX_DOWNLOAD_BYTES = 512 * 1024

# Default maximum text length returned to the LLM (to conserve context window)
DEFAULT_MAX_TEXT_LENGTH = 3500


class SafeHTMLTextExtractor(HTMLParser):
    """
    HTMLParser subclass that discards scripts, styles, metadata,
    and extracts only human-readable content and page title.
    """

    def __init__(self):
        super().__init__()
        self._current_tag = None
        self._skip_depth = 0
        self.title = ""
        self._in_title = False
        self.text_chunks = []

    def handle_starttag(self, tag, attrs):
        lower_tag = tag.lower()
        if lower_tag in ("script", "style", "noscript", "svg", "header", "footer", "nav"):
            self._skip_depth += 1
        elif lower_tag == "title":
            self._in_title = True
        elif lower_tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "article", "section"):
            self.text_chunks.append("\n")

    def handle_endtag(self, tag):
        lower_tag = tag.lower()
        if lower_tag in ("script", "style", "noscript", "svg", "header", "footer", "nav"):
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif lower_tag == "title":
            self._in_title = False
        elif lower_tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "article", "section"):
            self.text_chunks.append("\n")

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()
        elif self._skip_depth == 0:
            cleaned = data.strip()
            if cleaned:
                self.text_chunks.append(cleaned)

    def get_clean_text(self) -> str:
        raw_text = " ".join(self.text_chunks)
        # Normalize excessive whitespace and blank lines
        normalized = re.sub(r"[ \t]+", " ", raw_text)
        normalized = re.sub(r"\n\s*\n+", "\n\n", normalized)
        return normalized.strip()


def _is_safe_public_url(url: str) -> bool:
    """
    Security Guard: Validates that the URL uses HTTP/HTTPS and does not resolve
    to localhost, loopback, or private internal IP addresses (Anti-SSRF).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Block localhost aliases directly
        if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "10.0.2.2"):
            return False

        # Resolve hostname IP address to inspect IP range
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)

        # Disallow loopback, private, link-local, or multicast addresses
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False

        return True

    except Exception as e:
        logger.warning(f"URL security check failed for '{url}': {e}")
        return False


def scrape_webpage_content(url: str, max_chars: int = DEFAULT_MAX_TEXT_LENGTH) -> str:
    """
    Safely fetches a web page, strips HTML tags, and returns clean readable text.

    :param url: The full web address (e.g. 'https://en.wikipedia.org/wiki/Artificial_intelligence').
    :param max_chars: Maximum characters of text to return (default: 3500).
    :return: Formatted title and clean text extract, or an error description.
    """
    clean_url = (url or "").strip()
    if not clean_url:
        return "Error: URL parameter cannot be empty."

    # Prepend https:// if user passed a bare domain
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    # 1. Security Check against SSRF
    if not _is_safe_public_url(clean_url):
        logger.warning(f"Blocked unsafe or private URL request: {clean_url}")
        return (
            f"Security Policy: Access to '{clean_url}' is blocked. "
            "Only public HTTP/HTTPS web URLs may be scraped."
        )

    # 2. HTTP Fetch with size cap and realistic browser User-Agent
    req = urllib.request.Request(
        clean_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
    )

    try:
        logger.info(f"[SCRAPER]: Fetching content from {clean_url}")
        with urllib.request.urlopen(req, timeout=7) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type and "application/xhtml" not in content_type:
                return f"Notice: URL returned non-HTML content type '{content_type}'. Scraper currently only parses HTML/text."

            # Read capped byte amount
            raw_data = response.read(MAX_DOWNLOAD_BYTES)

        # Detect encoding
        encoding = "utf-8"
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[-1].split(";")[0].strip()

        decoded_html = raw_data.decode(encoding, errors="replace")

        # 3. Extract readable text using SafeHTMLTextExtractor
        parser = SafeHTMLTextExtractor()
        parser.feed(decoded_html)
        extracted_text = parser.get_clean_text()

        if not extracted_text:
            return f"Scraped '{clean_url}' successfully, but no readable body text was found."

        # Truncate to maximum characters
        truncated = False
        if len(extracted_text) > max_chars:
            extracted_text = extracted_text[:max_chars]
            truncated = True

        title_header = f"Page Title: {parser.title}\n" if parser.title else ""
        truncation_note = f"\n\n[... Truncated for length. Displaying {len(extracted_text)} characters.]" if truncated else ""

        return (
            f"--- Scraped Content from {clean_url} ---\n"
            f"{title_header}\n"
            f"{extracted_text}"
            f"{truncation_note}"
        )

    except urllib.error.HTTPError as http_err:
        logger.warning(f"HTTP error scraping {clean_url}: {http_err.code} {http_err.reason}")
        return f"Scraping Error: Server responded with HTTP {http_err.code} ({http_err.reason})."
    except urllib.error.URLError as url_err:
        logger.warning(f"Network error scraping {clean_url}: {url_err}")
        return f"Scraping Error: Unable to establish connection to '{clean_url}'."
    except TimeoutError:
        return f"Scraping Error: Request to '{clean_url}' timed out after 7 seconds."
    except Exception as exc:
        logger.error(f"Unexpected error scraping {clean_url}: {exc}", exc_info=True)
        return f"Scraping Error: {str(exc)}"
