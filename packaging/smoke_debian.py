"""Smoke-test the executable from a Debian archive without installing the app."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(package: Path) -> None:
    version = subprocess.check_output(["dpkg-deb", "-f", package, "Version"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="alln1-debian-") as temporary:
        base = Path(temporary)
        subprocess.run(["dpkg-deb", "-x", package, base / "package"], check=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = dict(os.environ, ALLINONE_HOME=str(base / "home"), ALLN1_DISABLE_UPDATE_CHECK="1",
                   NO_BROWSER="1", PORT=str(port))
        with subprocess.Popen([base / "package/opt/alln1downloader/AllN1Downloader"], env=env) as app:
            try:
                for _ in range(80):
                    if app.poll() is not None:
                        raise RuntimeError(f"Packaged app exited ({app.returncode})")
                    try:
                        with urlopen(url + "/api/health", timeout=2) as response:
                            health = json.load(response)
                        break
                    except URLError:
                        time.sleep(0.25)
                else:
                    raise RuntimeError("Packaged app did not start")
                assert health["version"] == version and health["ffmpeg"]
                assert Path(health["download_dir"]) == base / "home/downloads"
                with urlopen(url, timeout=5) as response:
                    assert b'id="analysisMode"' in response.read()
                body = json.dumps({"url": url + "/internal.pdf", "mode": "document"}).encode()
                try:
                    urlopen(Request(url + "/api/info", body, {"Content-Type": "application/json"}), timeout=10).close()
                except HTTPError as error:
                    assert error.code == 400 and "public address" in json.load(error)["detail"]
                else:
                    raise AssertionError("Original-file analysis did not deny a loopback target")
            finally:
                app.terminate()
                try:
                    app.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    app.kill()
                    app.wait()
    print(f"Debian {version}: packaged startup, asset delivery and file URL guard passed")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
