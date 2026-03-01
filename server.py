#!/usr/bin/env python3
"""
TDA Carousel Generator — local dev server.
Serves index.html and provides a /fetch endpoint that extracts
article text from a URL (bypasses browser CORS restrictions).
"""

import json
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
from html.parser import HTMLParser


def _load_dotenv():
    try:
        with open(os.path.join(os.path.dirname(__file__), '.env')) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass

_load_dotenv()


class ArticleExtractor(HTMLParser):
    """Pulls readable text out of an HTML page."""

    SKIP_TAGS = {
        'script', 'style', 'nav', 'footer', 'aside', 'noscript',
        'svg', 'button', 'form', 'iframe', 'header', 'figure',
        'figcaption', 'picture', 'select', 'option', 'textarea',
    }
    BLOCK_TAGS = {
        'p', 'h1', 'h2', 'h3', 'h4', 'h5',
        'blockquote', 'li', 'article', 'section', 'main',
    }

    def __init__(self):
        super().__init__()
        self.skip_depth  = 0
        self.block_depth = 0
        self.current     = []
        self.chunks      = []
        self.title       = ''
        self.in_title    = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        if tag == 'title':
            self.in_title = True
        if tag in self.BLOCK_TAGS and self.skip_depth == 0:
            self.block_depth += 1
            self.current = []

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag == 'title':
            self.in_title = False
        if tag in self.BLOCK_TAGS and self.block_depth > 0:
            self.block_depth -= 1
            text = ' '.join(self.current).strip()
            if len(text) > 25:
                self.chunks.append(text)
            self.current = []

    def handle_data(self, data):
        t = data.strip()
        if not t:
            return
        if self.in_title:
            self.title += t
            return
        if self.skip_depth == 0 and self.block_depth > 0:
            self.current.append(t)

    def get_text(self):
        parts = []
        if self.title:
            parts.append(self.title.strip())
        parts.extend(self.chunks)
        return '\n\n'.join(parts)


class Handler(SimpleHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors(200)

    def do_GET(self):
        from urllib.parse import urlparse
        parsed = urlparse(self.path)
        if parsed.path == '/image':
            self._handle_image(parsed)
        elif parsed.path == '/news':
            self._handle_news()
        else:
            super().do_GET()

    def _handle_news(self):
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        feeds = [
            'https://news.google.com/rss?hl=en-AU&gl=AU&ceid=AU:en',
        ]
        all_stories = []
        now = datetime.now(timezone.utc)

        for feed_url in feeds:
            try:
                req = urllib.request.Request(feed_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    xml_data = resp.read()

                root = ET.fromstring(xml_data)
                channel = root.find('channel') or root
                for item in channel.findall('item')[:12]:
                    title = (item.findtext('title') or '').strip()
                    link  = (item.findtext('link')  or '').strip()
                    pub   = (item.findtext('pubDate') or '').strip()
                    src_el = item.find('source')
                    source = src_el.text.strip() if src_el is not None else ''

                    # Strip " - Source Name" suffix from Google News titles
                    if ' - ' in title:
                        parts  = title.rsplit(' - ', 1)
                        title  = parts[0].strip()
                        if not source:
                            source = parts[1].strip()

                    try:
                        diff   = now - parsedate_to_datetime(pub)
                        mins   = int(diff.total_seconds() / 60)
                        time_ago = (f'{mins}m ago' if mins < 60
                                    else f'{mins//60}h ago' if mins < 1440
                                    else 'Yesterday')
                    except Exception:
                        time_ago = ''

                    all_stories.append({
                        'title':   title,
                        'url':     link,
                        'timeAgo': time_ago,
                        'source':  source,
                    })
            except Exception as e:
                print(f'  RSS error: {e}')

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'stories': all_stories[:10]}).encode())

    def _handle_image(self, parsed):
        from urllib.parse import parse_qs, quote
        params  = parse_qs(parsed.query)
        query   = params.get('q', ['australia'])[0]
        img_url = self._wikipedia_image(query) or self._flickr_image(query)

        if not img_url:
            self.send_response(502)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            return

        try:
            req = urllib.request.Request(img_url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=14) as resp:
                img_data     = resp.read()
                content_type = resp.headers.get('Content-Type', 'image/jpeg')
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(img_data)
        except Exception:
            self.send_response(502)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def _wikipedia_image(self, query):
        """Search Wikipedia for a relevant article thumbnail."""
        from urllib.parse import quote
        try:
            # 1. Search for best-matching article
            search_url = (
                'https://en.wikipedia.org/w/api.php?action=query&list=search'
                f'&srsearch={quote(query)}&format=json&srlimit=3'
            )
            req = urllib.request.Request(search_url, headers={'User-Agent': 'TDA-Carousel/1.0'})
            with urllib.request.urlopen(req, timeout=6) as r:
                results = json.loads(r.read()).get('query', {}).get('search', [])
            if not results:
                return None

            # 2. Get the page image for the top result
            title = results[0]['title']
            img_url = (
                'https://en.wikipedia.org/w/api.php?action=query'
                f'&titles={quote(title)}&prop=pageimages&format=json&pithumbsize=1200'
            )
            req = urllib.request.Request(img_url, headers={'User-Agent': 'TDA-Carousel/1.0'})
            with urllib.request.urlopen(req, timeout=6) as r:
                pages = json.loads(r.read()).get('query', {}).get('pages', {})
            for page in pages.values():
                src = page.get('thumbnail', {}).get('source')
                if src:
                    # Scale up to largest available version
                    import re
                    src = re.sub(r'/\d+px-', '/1200px-', src)
                    return src
        except Exception:
            pass
        return None

    def _flickr_image(self, query):
        keyword = query.replace(' ', ',')[:80]
        return f'https://loremflickr.com/800/1000/{keyword}'

    def do_POST(self):
        if self.path == '/generate':
            self._handle_generate()
            return
        if self.path != '/fetch':
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        try:
            url = json.loads(body).get('url', '').strip()
            if not url:
                raise ValueError('No URL provided')

            req = urllib.request.Request(url, headers={
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-AU,en;q=0.9',
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                charset = 'utf-8'
                ct = resp.headers.get_content_charset()
                if ct:
                    charset = ct
                html = resp.read().decode(charset, errors='ignore')

            extractor = ArticleExtractor()
            extractor.feed(html)
            text = extractor.get_text()

            if len(text) < 100:
                raise ValueError(
                    'Could not extract enough text from that page. '
                    'The site may block scrapers — try pasting the article text directly.'
                )

            self._cors(200)
            self.wfile.write(json.dumps({'text': text}).encode())

        except Exception as e:
            self._cors(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    def _handle_generate(self):
        ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
        try:
            length = int(self.headers.get('Content-Length', 0))
            body   = json.loads(self.rfile.read(length))
            prompt = body.get('prompt', '')

            payload = json.dumps({
                'model': 'claude-sonnet-4-6',
                'max_tokens': 2048,
                'messages': [{'role': 'user', 'content': prompt}]
            }).encode()

            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': ANTHROPIC_API_KEY,
                    'anthropic-version': '2023-06-01',
                }
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())

            self._cors(200)
            self.wfile.write(json.dumps(result).encode())

        except urllib.error.HTTPError as e:
            body = e.read().decode()
            self._cors(e.code)
            self.wfile.write(body.encode())
        except Exception as e:
            self._cors(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    def _cors(self, status):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f'  {self.address_string()} — {fmt % args}')


if __name__ == '__main__':
    port   = 8080
    server = HTTPServer(('', port), Handler)
    print(f'\n  TDA Carousel Generator → http://localhost:{port}\n')
    server.serve_forever()
