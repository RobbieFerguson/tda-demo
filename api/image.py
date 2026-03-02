from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, quote
import json, re, urllib.request

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        query  = params.get('q', ['australia'])[0]
        url    = self._wikipedia_image(query) or self._commons_image(query) or self._flickr_image(query)

        if not url:
            self.send_response(404); self.end_headers(); return

        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=14) as resp:
                data = resp.read()
                ct   = resp.headers.get('Content-Type', 'image/jpeg')
            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(502); self.end_headers()

    def _wikipedia_image(self, query):
        try:
            s_url = (
                'https://en.wikipedia.org/w/api.php?action=query&list=search'
                f'&srsearch={quote(query)}&format=json&srlimit=5'
            )
            req = urllib.request.Request(s_url, headers={'User-Agent': 'TDA-Carousel/1.0'})
            with urllib.request.urlopen(req, timeout=6) as r:
                results = json.loads(r.read()).get('query', {}).get('search', [])
            if not results: return None

            # Sort by overlap; only use articles sharing at least 1 query word
            q_words = set(query.lower().split())
            results.sort(
                key=lambda r: len(set(r['title'].lower().split()) & q_words),
                reverse=True
            )
            results = [r for r in results if len(set(r['title'].lower().split()) & q_words) >= 2]
            if not results: return None

            for result in results[:4]:
                title = result['title']
                i_url = (
                    f'https://en.wikipedia.org/w/api.php?action=query'
                    f'&titles={quote(title)}&prop=pageimages&format=json&pithumbsize=1200'
                )
                req = urllib.request.Request(i_url, headers={'User-Agent': 'TDA-Carousel/1.0'})
                with urllib.request.urlopen(req, timeout=6) as r:
                    pages = json.loads(r.read()).get('query', {}).get('pages', {})
                for page in pages.values():
                    src = page.get('thumbnail', {}).get('source')
                    if src:
                        return re.sub(r'/\d+px-', '/1200px-', src)
        except Exception:
            pass
        return None

    def _commons_image(self, query):
        try:
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
            skip_words = {'logo','flag','icon','map','diagram','coat','seal','emblem','symbol'}
            for page in sorted(pages.values(), key=lambda p: int(p.get('index', 9999))):
                info  = (page.get('imageinfo') or [{}])[0]
                mime  = info.get('mime', '')
                thumb = info.get('thumburl') or info.get('url', '')
                title = page.get('title', '').lower()
                if mime == 'image/svg+xml' or not thumb:
                    continue
                if any(w in title for w in skip_words):
                    continue
                return thumb
        except Exception:
            pass
        return None

    def _flickr_image(self, query):
        return f'https://loremflickr.com/800/1000/{query.replace(" ", ",")[:80]}'

    def log_message(self, *a): pass
