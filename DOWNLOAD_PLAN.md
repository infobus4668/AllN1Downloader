# AllN1Downloader: video, audio, images, and documents

## Product goal

Paste one link or a mixed batch, choose **Auto**, **Video**, **Audio**, **Images**,
or **Documents**, preview the available files, and download the selected items.
All types share the existing queue, progress, cancellation, retry, duplicate
detection, and Save/ZIP actions on Windows, Android, and Debian/Ubuntu.

## Open-source integrations

| Use case | Engine or source adapter | Initial scope |
|---|---|---|
| Video and audio pages or streams | yt-dlp and FFmpeg | Keep the existing site coverage, format options, subtitles, and audio conversion. |
| Direct HTTP(S) file links | Shared streaming file downloader | Fetch original videos, audio, images, and documents, including URLs with no file extension. |
| Image posts, galleries, and albums | Wikimedia Commons API and public-page file discovery | Preview and select individual Commons category items or eligible image links published on a page. |
| Open collections and publications | Official source APIs where available | Start with Wikimedia Commons, Internet Archive, and arXiv. Show individual files or formats and retain source and license metadata when provided. |
| Public document pages | Bounded linked-file discovery | From one page, list eligible file links for explicit selection. Direct cloud download links work when the service returns a supported file. |

The GPL-2.0-only gallery-dl library is not bundled with the GPL-3.0 Android app.
The same Requests-based file and public-source adapters are used on all platforms.
Dedicated adapters for other social galleries, cloud share pages and site-specific
authentication are future coverage, not built-in support.

Check each engine's license, dependency packaging, and behavior on all three
platforms before bundling it. Keep a tested source matrix; distinguish documented
upstream support from integrations verified in AllN1Downloader. The adapter
interface should allow additional maintained open-source engines and sources to
be added when they fill a coverage gap.

## Implementation order

1. **Shared file model and direct downloads.** Give analysis a typed list of
   downloadable items with name, kind, format, and optional size or dimensions.
   Keep existing video/audio job history compatible. Add direct downloads for
   JPEG, PNG, WebP, GIF, PDF, TXT, CSV, EPUB, modern Office, and OpenDocument
   files, plus common video and audio formats. Detect the file from the response
   and show a clear error when the server sends a sign-in page or a different file.
2. **Gallery and open-collection integrations.** Add the Wikimedia Commons
   gallery adapter and public archive/document adapters. Support selecting items from mixed
   collections, previewing images, and exporting selected files as a ZIP.
   Route supported video and audio items through the appropriate existing engine.
3. **Mixed batches and platform finish.** Allow a batch with different link types
   to assign a mode to each link. Show why a particular link failed while keeping
   successful jobs queued. Verify downloads and exports on each packaged build,
   including Android Downloads and opening saved documents with the OS handler.

## File handling and QA

- Use the same progress and cancellation model across engines. Stream files,
  enforce size limits, sanitize names, and make completed files visible only
  after the transfer succeeds. Keep gallery scans bounded and credentials in
  memory; restrict cookie use to the relevant source.
- Test extensionless URLs, redirects, mislabeled files, interrupted transfers,
  duplicate filenames, expired credentials, and mixed collections. Keep video
  and audio regression tests alongside the new cases.
- Run live checks on several independent hosts as well as local fixtures. Before
  release, exercise download and export from the signed Windows and Android
  packages and the Debian package. Publish the verified source matrix and note
  any site or platform limitations in the release notes.

## Live checks for 1.1.0

| Source | Verified outcome |
|---|---|
| Wikimedia Commons | Downloaded a JPEG from a file page and from the Apollo 17 Earth photography category. |
| arXiv | Downloaded a PDF starting from its public abstract page. |
| Internet Archive | Listed a mixed public LibriVox item and downloaded an original image. |
| W3C | Downloaded the direct public PDF test file. |
| MDN | Downloaded original MP4 video and MP3 audio from public example URLs. |
| OpenStreetMap | Downloaded a public PNG tile. |
| Python.org | Found a linked text document on the public license page and saved it. |

These checks exercise the shared backend. Fixture tests cover public-address
validation, redirect handling, queueing, file type checks and export.
Sources can change independently of the app. Login-protected pages, arbitrary
cloud share URLs, and social galleries without a verified adapter are not
guaranteed to resolve. Try the direct file URL when a provider offers one.
