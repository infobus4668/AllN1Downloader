"""Local release checks. No external media, browser cookies or live job history used."""
import asyncio
import functools
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

os.environ.setdefault('ALLN1_DISABLE_UPDATE_CHECK', '1')
import app

ROOT = Path(app.__file__).parent


class QueueTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.home = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch.multiple(app, jobs={}, DOWNLOAD_DIR=self.home, STATE_FILE=self.home / 'jobs.json'))

    def test_frozen_work_dir_is_persistent_and_user_writable(self):
        with patch.object(app.sys, 'frozen', True, create=True), patch.dict(
            os.environ, {'ALLINONE_HOME': '', 'LOCALAPPDATA': str(self.home)}
        ):
            self.assertEqual(app.default_work_dir(), self.home / 'AllInOne')
        override = self.home / 'custom-data'
        with patch.dict(os.environ, {'ALLINONE_HOME': str(override)}):
            self.assertEqual(app.default_work_dir(), override)

    def test_cancel_then_retry_runs_one_attempt(self):
        # Hold the only worker so cancellation deterministically precedes pickup.
        release = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as worker, patch.object(app, 'EXECUTOR', worker), patch.object(app, 'run_job') as run:
            worker.submit(release.wait, 5)
            try:
                job_id = app.create_download(app.DownloadRequest(url='https://example.com/video'))['id']
                self.assertEqual(app.cancel_job(job_id)['status'], 'cancelled')
                app.retry_job(job_id)
            finally:
                release.set()
            app.jobs[job_id].future.result(timeout=5)
            run.assert_called_once_with(app.jobs[job_id])

    def test_interrupted_job_and_unreadable_history(self):
        app.STATE_FILE.write_text('[incomplete', encoding='utf-8')
        with self.assertLogs(level='WARNING'):
            app.load_jobs()
        self.assertEqual(next(self.home.glob('jobs-unreadable-*.json')).read_text(), '[incomplete')
        app.STATE_FILE.write_text(json.dumps([dict(id='test123', url='https://example.com/video', options={}, status='downloading')]))
        app.load_jobs()
        self.assertEqual(app.jobs['test123'].status, 'error')
        self.assertIn('Retry', app.jobs['test123'].error)
        restored = app.jobs['test123']
        self.assertTrue(restored.to_dict()['can_retry'])
        pending = Future()
        restored.future = pending
        self.assertFalse(restored.to_dict()['can_retry'])
        pending.set_result(None)
        self.assertTrue(restored.to_dict()['can_retry'])

    def test_open_file_selects_media_not_sidecar(self):
        job = app.Job('https://example.com/video', {})
        app.jobs[job.id] = job
        job.status = 'completed'
        (job.dir / 'captions.srt').touch()
        media = job.dir / 'video.mkv'
        media.touch()
        self.assertTrue(job.to_dict()['has_playable'])
        with patch.object(app, 'open_path') as opener:
            app.open_job_file(job.id)
            opener.assert_called_once_with(media)
            with self.assertRaises(app.HTTPException):
                app.open_job_file(job.id, 'captions.srt')
            self.assertEqual(opener.call_count, 1)
            self.assertTrue(app.reveal_job(job.id)['ok'])
            opener.assert_called_with(job.dir)
        with patch.object(app, 'open_path') as opener:
            self.assertTrue(app.open_downloads()['ok'])
            opener.assert_called_once_with(self.home)
        with patch.object(app, 'ANDROID_MODE', True):
            self.assertEqual(app.open_job_file(job.id), {'ok': True, 'path': str(media)})
            self.assertEqual(app.reveal_job(job.id), {'ok': True, 'path': str(job.dir)})
            self.assertEqual(app.open_downloads(), {'ok': True, 'path': str(self.home)})

        sidecar_only = app.Job('https://example.com/captions', {})
        app.jobs[sidecar_only.id] = sidecar_only
        sidecar_only.status = 'completed'
        (sidecar_only.dir / 'captions.srt').touch()
        self.assertFalse(sidecar_only.to_dict()['has_playable'])

    def test_clear_finished_removes_terminal_files_only(self):
        finished = app.Job('https://example.com/done', {})
        active = app.Job('https://example.com/active', {})
        app.jobs[finished.id] = finished
        app.jobs[active.id] = active
        finished.status = 'completed'
        active.status = 'downloading'
        finished_file = finished.dir / 'done.mp4'
        active_file = active.dir / 'partial.mp4'
        finished_file.write_bytes(b'done')
        active_file.write_bytes(b'partial')
        self.assertEqual(app.clear_finished(), {'removed': 1})
        self.assertNotIn(finished.id, app.jobs)
        self.assertFalse(finished.dir.exists())
        self.assertIn(active.id, app.jobs)
        self.assertTrue(active_file.is_file())

    def test_clip_time_parsing_and_options(self):
        self.assertEqual(app.parse_clip_time('90', 'start'), 90.0)
        self.assertEqual(app.parse_clip_time('1:30', 'start'), 90.0)
        self.assertEqual(app.parse_clip_time('01:02:03.5', 'end'), 3723.5)
        self.assertIsNone(app.parse_clip_time('', 'start'))
        for value in ('1:75', 'abc', '-1', '1::2', '1:2:3:4'):
            with self.assertRaises(app.HTTPException):
                app.parse_clip_time(value, 'start')
        job = app.Job('https://example.com/video', {
            'mode': 'video', 'quality': 'best', 'container': 'mp4',
            'clip_start': 5.0, 'clip_end': 10.0, 'clip_precise': True,
        })
        options = app.build_ydl_options(job)
        self.assertTrue(options['force_keyframes_at_cuts'])
        self.assertEqual(options['download_ranges']({'duration': 100}, None), [{'start_time': 5.0, 'end_time': 10.0}])
        with self.assertRaises(app.yt_dlp.utils.DownloadError):
            options['download_ranges']({'duration': 4}, None)
        open_ended = app.Job('https://example.com/video', {
            'mode': 'audio', 'quality': 'best', 'container': 'mp3', 'clip_start': 3.0,
        })
        options = app.build_ydl_options(open_ended)
        self.assertFalse(options['force_keyframes_at_cuts'])
        self.assertEqual(options['download_ranges']({'duration': 12}, None), [{'start_time': 3.0, 'end_time': 12.0}])
        with patch.object(app, 'ANDROID_MODE', True), patch.object(app, 'FFMPEG', '/app/libffmpeg.so'):
            mobile_options = app.build_ydl_options(app.Job('https://example.com/video', {
                'mode': 'video', 'quality': 'best', 'container': 'mp4',
            }))
            self.assertEqual(mobile_options['ffmpeg_location'], '/app/libffmpeg.so')
        with self.assertRaises(app.HTTPException) as playlist_clip:
            app.create_download(app.DownloadRequest(
                url='https://example.com/list', is_playlist=True, playlist_items=[1],
                clip_start='1:00', clip_end='2:00',
            ))
        self.assertEqual(playlist_clip.exception.status_code, 400)
        with self.assertRaises(app.HTTPException):
            app.create_download(app.DownloadRequest(url='https://example.com/video', clip_start='2:00', clip_end='1:00'))

    def test_forget_keeps_downloaded_files(self):
        job = app.Job('https://example.com/video', {'mode': 'video'})
        app.jobs[job.id] = job
        job.status = 'completed'
        media = job.dir / 'video.mp4'
        media.write_bytes(b'media fixture')
        self.assertTrue(app.forget_job(job.id)['ok'])
        self.assertNotIn(job.id, app.jobs)
        self.assertTrue(media.is_file())
        job.status = 'downloading'
        app.jobs[job.id] = job
        with self.assertRaises(app.HTTPException):
            app.forget_job(job.id)

    def test_duplicate_download_requires_force(self):
        release = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as worker, patch.object(app, 'EXECUTOR', worker), patch.object(app, 'run_job'):
            worker.submit(release.wait, 5)
            first = app.create_download(app.DownloadRequest(url='https://example.com/video'))
            with self.assertRaises(app.HTTPException) as caught:
                app.create_download(app.DownloadRequest(url='https://example.com/video'))
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail['job_id'], first['id'])
            with self.assertRaises(app.HTTPException) as ineffective_precise:
                app.create_download(app.DownloadRequest(url='https://example.com/video', clip_precise=True))
            self.assertEqual(ineffective_precise.exception.detail['job_id'], first['id'])
            jobs = [first, app.create_download(app.DownloadRequest(url='https://example.com/video', force=True))]
            if app.FFMPEG:
                jobs.append(app.create_download(app.DownloadRequest(url='https://example.com/video', clip_start='1:00')))
            release.set()
            for job in jobs:
                app.jobs[job['id']].future.result(timeout=5)

    @unittest.skipUnless(app.FFPROBE, 'ffprobe is not available')
    def test_probe_media_reports_audio_stream(self):
        path = self.home / 'tone.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(bytes(16000))
        media = app.probe_media(path)
        self.assertIsNotNone(media)
        self.assertEqual(media['audio']['codec'], 'wav')
        self.assertGreater(media['duration'], 0.5)

    def test_interrupted_export_closes_only_its_archive(self):
        job = app.Job('https://example.com/video', {})
        app.jobs[job.id] = job
        job.status = 'completed'
        (job.dir / 'clip.mp4').write_bytes(b'media fixture')
        first = app.download_zip(job.id)
        self.addCleanup(first.output.close)
        second = app.download_zip(job.id)
        self.addCleanup(second.output.close)

        async def disconnected(_message):
            raise OSError('client disconnected')

        from starlette.requests import ClientDisconnect
        with self.assertRaises(ClientDisconnect):
            asyncio.run(first({'asgi': {'spec_version': '2.4'}, 'type': 'http'}, None, disconnected))
        self.assertTrue(first.output.closed)
        with zipfile.ZipFile(second.output) as archive:
            self.assertEqual(archive.read('clip.mp4'), b'media fixture')
        self.assertTrue((job.dir / 'clip.mp4').is_file())


@contextmanager
def running_app(home):
    # Run the real launcher on a separate port, with its own writable directory.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = dict(os.environ, ALLINONE_HOME=str(home), NO_BROWSER='1', PORT=str(port))
    proc = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    try:
        for _ in range(150):
            if proc.poll() is not None:
                raise RuntimeError('Test service exited before startup')
            try:
                if api(base, '/api/health')['download_dir'] == str(home / 'downloads'):
                    break
            except URLError:
                time.sleep(.1)
        else:
            raise RuntimeError('Test service did not start')
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def api(base, path, body=None, method=None):
    req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                  method=method, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


class ReleaseSmoke(unittest.TestCase):
    def test_download_export_and_restart(self):
        self.assertTrue(app.FFMPEG, 'Install FFmpeg before running the release suite')
        home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        source_dir = home / 'source'
        source_dir.mkdir()
        with wave.open(str(source_dir / 'tone.wav'), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(bytes(32000 * 4))
        source = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(SimpleHTTPRequestHandler, directory=str(source_dir)))
        self.addCleanup(source.server_close)
        threading.Thread(target=source.serve_forever, daemon=True).start()
        self.addCleanup(source.shutdown)
        url = f'http://127.0.0.1:{source.server_port}/tone.wav'
        with running_app(home) as base:
            with self.assertRaises(HTTPError) as invalid:
                api(base, '/api/info', {'url': url, 'proxy': 'invalid'})
            self.assertEqual(invalid.exception.code, 400)
            invalid.exception.close()
            self.assertTrue(api(base, '/api/info', {'url': url})['audio_only'])
            job = api(base, '/api/download', {'url': url, 'mode': 'audio', 'container': 'mp3'})
            path = '/api/jobs/' + job['id']
            for _ in range(200):
                job = api(base, path)
                if job['status'] in app.TERMINAL_STATUSES:
                    break
                time.sleep(.1)
            self.assertEqual(job['status'], 'completed', job.get('error'))
            self.assertIsNotNone(job.get('media'), 'ffprobe verification should populate media specs')
            self.assertEqual(job['media']['audio']['codec'], 'mp3')
            self.assertGreater(job['media']['duration'], 0.5)
            with urlopen(base + path + '/zip') as response, zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                name, = archive.namelist()
                self.assertTrue(name.endswith('.mp3'))
                self.assertGreater(len(archive.read(name)), 0)
            with urlopen(base + path + '/files/' + quote(name, safe='')) as response:
                self.assertGreater(len(response.read()), 0)
            probe = shutil.which('ffprobe')
            self.assertTrue(probe, 'Install ffprobe alongside FFmpeg')
            codec = subprocess.check_output([probe, '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', str(home / 'downloads' / job['id'] / name)], text=True)
            self.assertEqual(codec.strip(), 'mp3')
            # Completion is persisted asynchronously as the worker exits.
            for _ in range(50):
                if json.loads((home / 'data/jobs.json').read_text(encoding='utf-8'))[0]['status'] == 'completed':
                    break
                time.sleep(.1)
            if browser := os.getenv('SMOKE_BROWSER'):
                subprocess.run(['node', 'tests/browser.mjs', browser, base, url], cwd=ROOT, check=True, timeout=60)
            with self.assertRaises(HTTPError) as duplicate:
                api(base, '/api/download', {'url': url, 'mode': 'audio', 'container': 'mp3'})
            self.assertEqual(duplicate.exception.code, 409)
            self.assertEqual(json.loads(duplicate.exception.read())['detail']['job_id'], job['id'])
            duplicate.exception.close()
            clipped = api(base, '/api/download', {
                'url': url, 'mode': 'audio', 'container': 'original',
                'clip_start': '0:01', 'clip_end': '2.5',
            })
            clipped_path = '/api/jobs/' + clipped['id']
            for _ in range(300):
                clipped = api(base, clipped_path)
                if clipped['status'] in app.TERMINAL_STATUSES:
                    break
                time.sleep(.1)
            self.assertEqual(clipped['status'], 'completed', clipped.get('error'))
            self.assertGreater(clipped['media']['duration'], 0.9)
            self.assertLess(clipped['media']['duration'], 2.4)
        with running_app(home) as base:
            self.assertEqual(api(base, path)['status'], 'completed')
            self.assertEqual(api(base, clipped_path)['status'], 'completed')
            self.assertTrue(api(base, path, method='DELETE')['ok'])
            self.assertFalse((home / 'downloads' / job['id']).exists())
            self.assertTrue(api(base, clipped_path + '/forget', method='POST')['ok'])
            self.assertTrue(any((home / 'downloads' / clipped['id']).iterdir()))
            with self.assertRaises(HTTPError) as forgotten:
                api(base, clipped_path)
            self.assertEqual(forgotten.exception.code, 404)
            forgotten.exception.close()


if __name__ == '__main__':
    unittest.main()
