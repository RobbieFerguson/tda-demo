from http.server import BaseHTTPRequestHandler
import xml.etree.ElementTree as ET
import re as _re
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
import json, urllib.request

FEEDS = [
    ('https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en',      'Google News'),
    ('https://feeds.bbci.co.uk/news/rss.xml',                       'BBC News'),
    ('https://feeds.bbci.co.uk/news/world/rss.xml',                 'BBC World'),
    ('https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en', 'World News'),
]

STOP = {'a','an','the','in','on','at','to','for','of','and','or','but',
        'is','are','was','were','has','have','had','be','by','as','with',
        'its','it','this','that','will','from','up','out','over','new',
        'us','uk','not','who','what','how','says','said','after','about'}

def key_words(t):
    return set(w for w in _re.sub(r'[^\w\s]','',t.lower()).split()
               if w not in STOP and len(w) > 2)

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        now    = datetime.now(timezone.utc)
        raw    = []

        for feed_url, feed_name in FEEDS:
            try:
                req = urllib.request.Request(
                    feed_url, headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    root = ET.fromstring(resp.read())

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
                        mins = int((now - dt).total_seconds() / 60)
                    except Exception:
                        dt   = now
                        mins = 0

                    raw.append({'title': title, 'url': link, 'source': source,
                                'dt': dt, 'mins': mins})
            except Exception:
                pass

        # Deduplicate: merge stories sharing 2+ key words, count coverage
        stories   = []
        kw_groups = []
        for s in raw:
            kw     = key_words(s['title'])
            merged = False
            for i, (grp_kw, grp_idx) in enumerate(kw_groups):
                if len(kw & grp_kw) >= 2:
                    stories[grp_idx]['score'] += 1
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

        result = []
        for s in stories[:12]:
            m = s['mins']
            time_ago = (f'{m}m ago' if m < 60
                        else f'{m//60}h ago' if m < 1440
                        else 'Yesterday')
            result.append({'title': s['title'], 'url': s['url'],
                           'timeAgo': time_ago, 'source': s['source']})

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'stories': result}).encode())

    def log_message(self, *a): pass
