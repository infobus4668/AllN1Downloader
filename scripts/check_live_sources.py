"""Opt-in live QA against a locally running AllN1Downloader instance."""
import argparse
import concurrent.futures
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


# Public samples. Only explicitly selected examples are queued for download.
CASES = (
    ('Instagram Reel', 'https://www.instagram.com/reel/DKgSMRwuPpp/', 'auto', True),
    ('X photo', 'https://x.com/9AgentAI/status/2125874715093012853/photo/1', 'auto', True),
    ('YouTube', 'https://www.youtube.com/watch?v=jNQXAC9IVRw', 'video', True),
    ('TikTok', 'https://www.tiktok.com/@scout2015/video/6718335390845095173', 'video', False),
    ('TikTok alternate post', 'https://www.tiktok.com/@hankgreen1/video/7047596209028074758', 'video', False),
    ('Vimeo', 'https://vimeo.com/76979871', 'video', False),
    ('Vimeo public player', 'https://player.vimeo.com/video/76979871', 'video', True),
    ('Dailymotion', 'https://www.dailymotion.com/video/x84sh87', 'video', False),
    ('SoundCloud previous sample', 'https://soundcloud.com/odesza/say-my-name-feat-zyra', 'audio', False),
    ('SoundCloud alternate track', 'https://soundcloud.com/giovannisarani/mezzo-valzer', 'audio', True),
    ('Facebook', 'https://www.facebook.com/nasa/videos/10155636191516772/', 'video', False),
    ('Facebook alternate video', 'https://www.facebook.com/radiokicksfm/videos/3676516585958356/', 'video', False),
    ('Facebook public Reel', 'https://www.facebook.com/reel/1195289147628387', 'video', True),
    ('Reddit', 'https://www.reddit.com/r/videos/comments/dyg3fl/', 'video', False),
    ('Twitch previous clip', 'https://clips.twitch.tv/KindFairDumplingsCurseLit', 'video', False),
    ('Twitch alternate clip', 'https://clips.twitch.tv/FaintLightGullWholeWheat', 'video', True),
    ('Bilibili', 'https://www.bilibili.com/video/BV1xx411c7mD/', 'video', False),
    ('Bluesky video', 'https://bsky.app/profile/bsky.app/post/3l3vgf77uco2g', 'video', True),
    ('LinkedIn video', 'https://www.linkedin.com/posts/the-mathworks_2_what-is-mathworks-cloud-center-activity-7151241570371948544-4Gu7', 'video', False),
    ('Pinterest video', 'https://www.pinterest.com/pin/664281013778109217/', 'video', False),
    ('Tumblr video', 'https://shieldfoss.tumblr.com/post/675519763813908480', 'video', False),
    ('MDN MP4', 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4', 'auto', True),
    ('MDN WebM', 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.webm', 'auto', True),
    ('MDN MP3', 'https://interactive-examples.mdn.mozilla.net/media/cc0-audio/t-rex-roar.mp3', 'auto', True),
    ('Wikimedia image', 'https://commons.wikimedia.org/wiki/File:Example.jpg', 'image', True),
    ('W3C PDF', 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf', 'document', True),
    ('Python.org linked document', 'https://www.python.org/psf/license/', 'document', True),
    ('arXiv abstract', 'https://arxiv.org/abs/1706.03762', 'document', True),
    ('Internet Archive mixed item', 'https://archive.org/details/iliad_of_homer_1011_librivox', 'auto', False),
    ('OpenStreetMap image', 'https://tile.openstreetmap.org/0/0/0.png', 'image', True),
    ('Project Gutenberg EPUB', 'https://www.gutenberg.org/ebooks/11.epub3.images', 'document', True),
    ('Project Gutenberg mirror EPUB', 'https://gutenberg.pglaf.org/cache/epub/11/pg11-images.epub', 'document', True),
    ('Standard Ebooks EPUB', 'https://standardebooks.org/ebooks/lewis-carroll/alices-adventures-in-wonderland/john-tenniel/downloads/lewis-carroll_alices-adventures-in-wonderland_john-tenniel.epub', 'document', True),
    ('GitHub raw text', 'https://raw.githubusercontent.com/python/cpython/main/LICENSE', 'document', True),
    ('Vega CSV', 'https://raw.githubusercontent.com/vega/vega-datasets/main/data/seattle-weather.csv', 'document', True),
)


def api(base, path, body=None):
    request = Request(base + path, json.dumps(body).encode() if body is not None else None,
                      {'Content-Type': 'application/json'} if body is not None else {})
    try:
        with urlopen(request, timeout=55) as response:
            return json.load(response)
    except HTTPError as error:
        with error:
            detail = json.load(error).get('detail', error.reason)
        raise RuntimeError(str(detail)) from None


def check(base, case, download):
    label, url, mode, can_download = case
    try:
        info = api(base, '/api/info', {'url': url, 'mode': mode})
    except Exception as error:
        return label, 'analysis failed', str(error)
    kinds = sorted({entry['kind'] for entry in info.get('entries') or [] if 'kind' in entry})
    if mode == 'video' and not info.get('is_playlist') and not info.get('qualities'):
        return label, 'no video format', 'Analysis returned metadata without a selectable video stream'
    details = ', '.join(kinds) or ('playlist' if info.get('is_playlist') else 'audio' if info.get('audio_only') else 'video')
    if not download or not can_download:
        return label, 'analyzed', details
    selected_mode = mode if info.get('original_files') else ('audio' if mode == 'audio' or info.get('audio_only') else 'video')
    body = {'url': url, 'mode': selected_mode, 'container': 'original' if selected_mode == 'audio' else 'mp4',
            'original_files': bool(info.get('original_files')), 'force': True}
    if info.get('original_files'):
        body['file_keys'] = [info['entries'][0]['key']]
    try:
        job = api(base, '/api/download', body)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = api(base, '/api/jobs/' + job['id'])
            if job['status'] == 'completed' and job['files']:
                return label, 'downloaded', f"{details}; {sum(item['size'] for item in job['files'])} bytes"
            if job['status'] in ('error', 'cancelled'):
                return label, 'download failed', job.get('error') or job['status']
            time.sleep(1)
        return label, 'download timed out', job['id']
    except Exception as error:
        return label, 'download failed', str(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8768')
    parser.add_argument('--download', action='store_true', help='Queue the marked samples in this app instance')
    parser.add_argument('--match', default='', help='Run only cases whose label contains this string')
    args = parser.parse_args()
    from urllib.parse import urlsplit
    if urlsplit(args.base).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        parser.error('Use a loopback app instance')
    health = api(args.base, '/api/health')
    print(f"AllN1Downloader {health['version']}, yt-dlp {health['yt_dlp']}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(check, args.base, case, args.download)
                   for case in CASES if args.match.lower() in case[0].lower()]
        for task in concurrent.futures.as_completed(pending):
            label, status, detail = task.result()
            print(f'{label}: {status} — {detail}', flush=True)


if __name__ == '__main__':
    main()
