import gzip
import io
import json
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import app
import file_downloads as files


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/book.epub?source=download':
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                archive.writestr('META-INF/container.xml', '<container/>')
            body = buffer.getvalue()
            self.send_response(200)
            self.send_header('Content-Type', 'application/epub+zip')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        records = {
            '/page': ('text/html', b'<a href="/report.pdf">Report</a><a href="/image.png">Photo</a>'),
            '/gallery': ('text/html', b'<a href="/report.pdf">Report</a>' * 110 +
                         b'<img src="/placeholder.png" data-src="/image.png">'),
            '/report.pdf': ('application/pdf', b'%PDF-1.4\n% fixture\n%%EOF\n'),
            '/image.png': ('image/png', b'\x89PNG\r\n\x1a\nfixture'),
            '/extensionless': ('image/png', b'\x89PNG\r\n\x1a\nfixture'),
            '/fake.pdf': ('application/pdf', b'<html>Sign in</html>'),
            '/book.epub': ('application/xhtml+xml', b'<meta http-equiv="refresh" content="0; url=/book.epub?source=download" />'),
            '/other.epub': ('application/xhtml+xml', b'<meta http-equiv="refresh" content="0; url=https://example.com/other.epub?go=1" />'),
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

    def test_epub_handoff_follows_same_file_and_does_not_follow_external_page(self):
        with patch.object(files, 'public_url') as guard, files.session_for() as session:
            items, source = files.resolve_files(self.url + '/book.epub', 'document', session)
            self.assertEqual(source, 'Direct file')
            self.assertEqual(items[0].url, self.url + '/book.epub?source=download')
            files.save_file(items[0], session, self.root, lambda: False, lambda *_: None)
            self.assertTrue(zipfile.is_zipfile(self.root / 'book.epub'))
            self.assertFalse(files.resolve_files(self.url + '/other.epub', 'document', session)[0])
            self.assertTrue(all(call.args[0].startswith(self.url) for call in guard.call_args_list))

    def test_embedded_photo_is_downloadable_even_after_many_document_links(self):
        with patch.object(files, 'public_url'), files.session_for() as session:
            items, source = files.resolve_files(self.url + '/gallery', 'image', session)
            self.assertEqual(source, 'Page files')
            self.assertEqual([item.name for item in items], ['image.png'])
            files.save_file(items[0], session, self.root, lambda: False, lambda *_: None)
        self.assertTrue((self.root / 'image.png').read_bytes().startswith(b'\x89PNG'))

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

    def test_x_photo_selection_ignores_replies_avatars_and_video_thumbnails(self):
        rows = [
            {'type': 'photo', 'expanded_url': 'https://x.com/reply/status/456/photo/1',
             'media_url_https': 'https://pbs.twimg.com/media/reply.jpg'},
            {'type': 'photo', 'expanded_url': 'https://x.com/user/status/123/photo/1',
             'media_url_https': 'https://pbs.twimg.com/media/first.jpg'},
            {'type': 'photo', 'expanded_url': 'https://twitter.com/user/status/123/photo/2',
             'media_url_https': 'https://pbs.twimg.com/media/second?format=png&name=large'},
            {'type': 'video', 'expanded_url': 'https://x.com/user/status/123/photo/3',
             'media_url_https': 'https://pbs.twimg.com/media/third.jpg'},
            {'type': 'photo', 'expanded_url': 'https://x.com/user/status/123/photo/4',
             'media_url_https': 'https://pbs.twimg.com/profile_images/avatar.jpg'},
        ]
        page = '<script>bootstrap(' + json.dumps(json.dumps({'media_entities2': rows})) + ')</script>'
        self.assertEqual([item.name for item in files.x_post_photos(page, '123', None)], ['first.jpg', 'second.png'])
        selected = files.x_post_photos(page, '123', 2)
        self.assertEqual([item.url for item in selected], ['https://pbs.twimg.com/media/second?format=png&name=orig'])
        self.assertFalse(files.x_post_photos(page, '123', 3))
        self.assertFalse(files.x_post_photos(page, '123', 4))

    def test_x_first_photo_can_use_post_metadata_when_its_canonical_post_matches(self):
        page = ('<meta property="og:url" content="https://x.com/user/status/123">'
                '<meta property="og:image" content="https://pbs.twimg.com/media/photo?format=jpg&amp;name=large">')
        self.assertEqual([item.name for item in files.x_post_photos(page, '123', 1)], ['photo.jpg'])
        self.assertFalse(files.x_post_photos(page, '123', 2))
        self.assertFalse(files.x_post_photos(page, '789', 1))

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
