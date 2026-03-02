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
        import re as _re
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone, timedelta

        # Multiple global feeds — duplicates across feeds signal significance
        feeds = [
            ('https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en',      'Google News'),
            ('https://feeds.bbci.co.uk/news/rss.xml',                       'BBC News'),
            ('https://feeds.bbci.co.uk/news/world/rss.xml',                 'BBC World'),
            ('https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en', 'World News'),
        ]
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        raw    = []  # {title, url, source, dt, mins}

        STOP = {'a','an','the','in','on','at','to','for','of','and','or','but',
                'is','are','was','were','has','have','had','be','by','as','with',
                'its','it','this','that','will','from','up','out','over','new',
                'us','uk','not','who','what','how','says','said','after','about'}

        def key_words(t):
            return set(w for w in _re.sub(r'[^\w\s]','',t.lower()).split()
                       if w not in STOP and len(w) > 2)

        for feed_url, feed_name in feeds:
            try:
                req = urllib.request.Request(feed_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    xml_data = resp.read()

                root    = ET.fromstring(xml_data)
                channel = root.find('channel') or root
                for item in channel.findall('item')[:20]:
                    title  = (item.findtext('title')   or '').strip()
                    link   = (item.findtext('link')    or '').strip()
                    pub    = (item.findtext('pubDate')  or '').strip()
                    src_el = item.find('source')
                    source = src_el.text.strip() if src_el is not None else feed_name

                    if ' - ' in title:
                        parts  = title.rsplit(' - ', 1)
                        title  = parts[0].strip()
                        if not source or source == feed_name:
                            source = parts[1].strip()

                    try:
                        dt   = parsedate_to_datetime(pub)
                        diff = now - dt
                        mins = int(diff.total_seconds() / 60)
                    except Exception:
                        dt   = now
                        mins = 0

                    raw.append({'title': title, 'url': link, 'source': source,
                                'dt': dt, 'mins': mins})
            except Exception as e:
                print(f'  RSS error ({feed_name}): {e}')

        # Deduplicate: merge stories that share 2+ key words, count coverage
        stories   = []
        kw_groups = []
        for s in raw:
            kw = key_words(s['title'])
            merged = False
            for i, (grp_kw, grp_idx) in enumerate(kw_groups):
                if len(kw & grp_kw) >= 2:
                    stories[grp_idx]['score'] += 1
                    # Keep the most recent version of the title/url
                    if s['mins'] < stories[grp_idx]['mins']:
                        stories[grp_idx].update(
                            title=s['title'], url=s['url'],
                            source=s['source'], mins=s['mins'], dt=s['dt']
                        )
                    kw_groups[i] = (grp_kw | kw, grp_idx)
                    merged = True
                    break
            if not merged:
                stories.append({**s, 'score': 1})
                kw_groups.append((kw, len(stories) - 1))

        # Sort: coverage count desc, then recency desc
        stories.sort(key=lambda s: (-s['score'], s['mins']))

        # Format time_ago and return top 12
        result = []
        for s in stories[:12]:
            m = s['mins']
            time_ago = (f'{m}m ago'    if m < 60
                        else f'{m//60}h ago' if m < 1440
                        else 'Yesterday')
            result.append({'title': s['title'], 'url': s['url'],
                           'timeAgo': time_ago, 'source': s['source']})

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'stories': result}).encode())

    def _handle_image(self, parsed):
        from urllib.parse import parse_qs, quote
        params  = parse_qs(parsed.query)
        query   = params.get('q', ['australia'])[0]
        img_url = self._wikipedia_image(query) or self._commons_image(query) or self._flickr_image(query)

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
        import re
        try:
            # 1. Search for best-matching articles
            search_url = (
                'https://en.wikipedia.org/w/api.php?action=query&list=search'
                f'&srsearch={quote(query)}&format=json&srlimit=5'
            )
            req = urllib.request.Request(search_url, headers={'User-Agent': 'TDA-Carousel/1.0'})
            with urllib.request.urlopen(req, timeout=6) as r:
                results = json.loads(r.read()).get('query', {}).get('search', [])
            if not results:
                return None

            # Sort by word overlap; only keep articles with at least 1 matching word
            q_words = set(query.lower().split())
            results.sort(
                key=lambda r: len(set(r['title'].lower().split()) & q_words),
                reverse=True
            )
            results = [r for r in results if len(set(r['title'].lower().split()) & q_words) >= 2]
            if not results:
                return None

            # 2. Try each relevant candidate until we find one with an image
            for result in results[:4]:
                title = result['title']
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
                        src = re.sub(r'/\d+px-', '/1200px-', src)
                        return src
        except Exception:
            pass
        return None

    def _commons_image(self, query):
        """Search Wikimedia Commons for a relevant photograph."""
        from urllib.parse import quote
        import re
        try:
            # One-shot: search Commons files and return imageinfo in same call
            url = (
                'https://commons.wikimedia.org/w/api.php?action=query'
                f'&generator=search&gsrsearch={quote(query)}&gsrnamespace=6'
                '&prop=imageinfo&iiprop=url|mime&iiurlwidth=1200'
                '&format=json&gsrlimit=20'
            )
            req = urllib.request.Request(url, headers={'User-Agent': 'TDA-Carousel/1.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                pages = json.loads(r.read()).get('query', {}).get('pages', {})
            if not pages:
                return None
            skip = {'svg+xml'}
            skip_words = {'logo', 'flag', 'icon', 'map', 'diagram', 'coat', 'seal', 'emblem', 'symbol'}
            for page in sorted(pages.values(), key=lambda p: int(p.get('index', 9999))):
                info = (page.get('imageinfo') or [{}])[0]
                mime  = info.get('mime', '')
                thumb = info.get('thumburl') or info.get('url', '')
                title = page.get('title', '').lower()
                if mime in skip or not thumb:
                    continue
                if any(w in title for w in skip_words):
                    continue
                return thumb
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
