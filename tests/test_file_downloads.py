import gzip
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import app
import file_downloads as files


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        records = {
            '/page': ('text/html', b'<a href="/report.pdf">Report</a><a href="/image.png">Photo</a>'),
            '/report.pdf': ('application/pdf', b'%PDF-1.4\n% fixture\n%%EOF\n'),
            '/image.png': ('image/png', b'\x89PNG\r\n\x1a\nfixture'),
            '/extensionless': ('image/png', b'\x89PNG\r\n\x1a\nfixture'),
            '/fake.pdf': ('application/pdf', b'<html>Sign in</html>'),
            '/compressed.txt': ('text/plain', gzip.compress(b'<ordinary text>\n')),
            '/wrong.jpg': ('image/png', b'\x89PNG\r\n\x1a\nfixture'),
        }
        if self.path.startswith('/redirect'):
            self.send_response(302)
            self.send_header('Location', '/extensionless')
            self.end_headers()
            return
        if self.path not in records:
            self.send_error(404)
            return
        mime, body = records[self.path]
        self.send_response(200)
        self.send_header('Content-Type', mime)
        if self.path == '/compressed.txt':
            self.send_header('Content-Encoding', 'gzip')
        if self.path != '/extensionless':
            self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FileDownloadsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def test_direct_file_and_redirect_detection(self):
        with patch.object(files, 'public_url') as guard, files.session_for() as session:
            items, source = files.resolve_files(self.url + '/redirect', 'auto', session)
            self.assertEqual([call.args[0] for call in guard.call_args_list],
                             [self.url + '/redirect', self.url + '/extensionless'])
            self.assertEqual(source, 'Direct file')
            self.assertEqual(items[0].kind, 'image')
            self.assertIsNone(items[0].size)
            files.save_file(items[0], session, self.root, lambda: False, lambda *_: None)
            files.save_file(items[0], session, self.root, lambda: False, lambda *_: None)
        self.assertEqual({p.name for p in self.root.iterdir()}, {'extensionless.png', 'extensionless (1).png'})

    def test_bad_content_limit_and_cancel_leave_no_files(self):
        with patch.object(files, 'public_url'), files.session_for() as session:
            fake, _ = files.resolve_files(self.url + '/fake.pdf', 'document', session)
            with self.assertRaisesRegex(files.FileDownloadError, 'contents'):
                files.save_file(fake[0], session, self.root, lambda: False, lambda *_: None)
            valid, _ = files.resolve_files(self.url + '/extensionless', 'image', session)
            with self.assertRaisesRegex(files.FileDownloadError, 'limit'):
                files.save_file(valid[0], session, self.root, lambda: False, lambda *_: None, limit=8)
            with self.assertRaises(InterruptedError):
                files.save_file(valid[0], session, self.root, lambda: True, lambda *_: None)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_local_targets_are_rejected_by_default(self):
        with files.session_for() as session, self.assertRaisesRegex(files.FileDownloadError, 'public address'):
            files.resolve_files(self.url + '/report.pdf', 'document', session)

    def test_compressed_text_and_same_kind_mime_correction(self):
        with patch.object(files, 'public_url'), files.session_for() as session:
            for source, name, data in (
                ('/compressed.txt', 'compressed.txt', b'<ordinary text>\n'),
                ('/wrong.jpg', 'wrong.png', b'\x89PNG\r\n\x1a\nfixture'),
            ):
                items, _ = files.resolve_files(self.url + source, 'auto', session)
                files.save_file(items[0], session, self.root, lambda: False, lambda *_: None)
                self.assertEqual((self.root / name).read_bytes(), data)

    def test_collection_file_keys_distinguish_query_selected_files(self):
        a = files.FileItem('https://example.com/download?file=a', 'notes.pdf', 'document')
        b = files.FileItem('https://example.com/download?file=b', 'notes.pdf', 'document')
        self.assertNotEqual(app.file_key(a), app.file_key(b))

    def test_document_page_to_queue_to_export(self):
        state_file = self.root / 'jobs.json'
        with patch.object(files, 'public_url'), patch.multiple(app, jobs={}, DOWNLOAD_DIR=self.root, STATE_FILE=state_file):
            info = app.get_info(app.InfoRequest(url=self.url + '/page', mode='document'))
            self.assertTrue(info['original_files'])
            self.assertEqual([item['title'] for item in info['entries']], ['report.pdf'])
            queued = app.create_download(app.DownloadRequest(url=self.url + '/page', mode='document',
                original_files=True, file_keys=[info['entries'][0]['key']]))
            job = app.get_job(queued['id'])
            job.future.result(timeout=10)
            self.assertEqual(job.status, 'completed', job.error)
            self.assertTrue(job.to_dict()['has_openable'])
            response = app.download_file(job.id, 'report.pdf')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertTrue(Path(response.path).read_bytes().startswith(b'%PDF-'))
            self.assertEqual(json.loads(state_file.read_text())[0]['status'], 'completed')
