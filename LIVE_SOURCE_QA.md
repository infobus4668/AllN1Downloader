# Live source QA — November 26, 2026

Run the [public sample matrix](scripts/check_live_sources.py) against an isolated
local app instance. Analysis is the default. To also queue the marked samples:

```powershell
python scripts/check_live_sources.py --base http://127.0.0.1:8768 --download
```

Use `--match NAME` to rerun one group. The matrix uses no account credentials.
“Downloaded” means the app completed a queue job with a saved file; “analyzed”
does not imply a successful download. Results can change with the link, account,
region, or provider response.

| Result | Public samples checked |
|---|---|
| Social downloads completed | Instagram Reel `DKgSMRwuPpp`, X photo `2125874715093012853/photo/1`, YouTube, alternate SoundCloud track, alternate Twitch clip, Bluesky video, and an alternate public Facebook Reel `1195289147628387`. |
| General-site downloads completed | MDN MP4, WebM, and MP3; Wikimedia Commons JPEG; OpenStreetMap PNG; W3C PDF; arXiv PDF; linked text from Python.org; GitHub raw license text; Vega CSV; Standard Ebooks EPUB; and a Project Gutenberg EPUB from the PGLAF mirror. |
| Analysis succeeded; download not exercised in this pass | Dailymotion, Bilibili, Pinterest, LinkedIn, and an Internet Archive collection. |
| Source requested sign-in or refused access | The Vimeo watch page, the two original Facebook samples, Reddit, and the Tumblr sample. No signed-in QA was performed. |
| Other unresolved samples | Both TikTok sample pages omitted usable video data. The original Twitch clip and SoundCloud track were unavailable; their alternates worked. The primary Gutenberg EPUB URL continued returning HTTP 503; the PGLAF mirror downloaded successfully. The public Vimeo player analyzed successfully, but the downloader reported DRM during transfer. |

For the Instagram sample, the saved file was verified as 1080 × 1920 with VP9
video and AAC audio. The X sample was saved as a JPEG. These results cover the
listed URLs, not every post or every format a provider offers.

The Standard Ebooks sample first returns a download page with a same-file refresh.
The app now follows that single handoff and verifies the resulting EPUB.
