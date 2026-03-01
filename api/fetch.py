from http.server import BaseHTTPRequestHandler
from html.parser import HTMLParser
import json, urllib.request

class ArticleExtractor(HTMLParser):
    SKIP  = {'script','style','nav','footer','aside','noscript','svg','button',
              'form','iframe','header','figure','figcaption','picture','select','textarea'}
    BLOCK = {'p','h1','h2','h3','h4','h5','blockquote','li','article','section','main'}

    def __init__(self):
        super().__init__()
        self.skip=0; self.block=0; self.cur=[]; self.chunks=[]; self.title=''; self.in_title=False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag == 'title': self.in_title = True
        if tag in self.BLOCK and self.skip == 0: self.block += 1; self.cur = []

    def handle_endtag(self, tag):
        if tag in self.SKIP: self.skip = max(0, self.skip - 1)
        if tag == 'title': self.in_title = False
        if tag in self.BLOCK and self.block > 0:
            self.block -= 1
            t = ' '.join(self.cur).strip()
            if len(t) > 25: self.chunks.append(t)
            self.cur = []

    def handle_data(self, data):
        t = data.strip()
        if not t: return
        if self.in_title: self.title += t; return
        if self.skip == 0 and self.block > 0: self.cur.append(t)

    def get_text(self):
        parts = ([self.title.strip()] if self.title else []) + self.chunks
        return '\n\n'.join(parts)


class handler(BaseHTTPRequestHandler):

    def _cors(self, status):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self): self._cors(200)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body   = json.loads(self.rfile.read(length))
            url    = body.get('url', '').strip()
            if not url: raise ValueError('No URL provided')

            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-AU,en;q=0.9',
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                charset = resp.headers.get_content_charset() or 'utf-8'
                html = resp.read().decode(charset, errors='ignore')

            ex = ArticleExtractor(); ex.feed(html)
            text = ex.get_text()
            if len(text) < 100:
                raise ValueError('Could not extract enough text — try pasting the article directly.')

            self._cors(200)
            self.wfile.write(json.dumps({'text': text}).encode())
        except Exception as e:
            self._cors(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    def log_message(self, *a): pass
