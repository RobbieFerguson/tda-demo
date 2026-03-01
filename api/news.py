from http.server import BaseHTTPRequestHandler
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import json, urllib.request

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        now = datetime.now(timezone.utc)
        stories = []

        try:
            req = urllib.request.Request(
                'https://news.google.com/rss?hl=en-AU&gl=AU&ceid=AU:en',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())

            channel = root.find('channel') or root
            for item in channel.findall('item')[:12]:
                title  = (item.findtext('title')   or '').strip()
                link   = (item.findtext('link')    or '').strip()
                pub    = (item.findtext('pubDate') or '').strip()
                src_el = item.find('source')
                source = src_el.text.strip() if src_el is not None else ''

                if ' - ' in title:
                    parts = title.rsplit(' - ', 1)
                    title = parts[0].strip()
                    if not source:
                        source = parts[1].strip()

                try:
                    diff     = now - parsedate_to_datetime(pub)
                    mins     = int(diff.total_seconds() / 60)
                    time_ago = (f'{mins}m ago' if mins < 60
                                else f'{mins//60}h ago' if mins < 1440
                                else 'Yesterday')
                except Exception:
                    time_ago = ''

                stories.append({'title': title, 'url': link,
                                 'timeAgo': time_ago, 'source': source})
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'stories': stories[:10]}).encode())

    def log_message(self, *a): pass
