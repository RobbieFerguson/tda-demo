from http.server import BaseHTTPRequestHandler
import json, os, urllib.request, urllib.error

API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

class handler(BaseHTTPRequestHandler):

    def _cors(self, status):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self):
        self._cors(200)

    def do_POST(self):
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
                    'x-api-key': API_KEY,
                    'anthropic-version': '2023-06-01',
                }
            )
            with urllib.request.urlopen(req, timeout=55) as resp:
                result = resp.read()
            self._cors(200)
            self.wfile.write(result)

        except urllib.error.HTTPError as e:
            self._cors(e.code)
            self.wfile.write(e.read())
        except Exception as e:
            self._cors(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    def log_message(self, *a): pass
