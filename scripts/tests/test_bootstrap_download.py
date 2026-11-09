#!/usr/bin/env python3
"""Offline tests for transient HTTP failures during bootstrap downloads."""
import sys
import hashlib
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_bootstrap as pb


def http_error(code):
    return urllib.error.HTTPError('https://example.invalid/asset', code, 'error', {}, None)


class DownloadRetries(unittest.TestCase):
    @patch.object(pb.time, 'sleep')
    @patch.object(pb, 'http_download_once')
    def test_504_then_success(self, download, sleep):
        download.side_effect = [http_error(504), None]
        pb.http_download('https://example.invalid/asset', Path('asset.zip'))
        self.assertEqual(download.call_count, 2)
        sleep.assert_called_once_with(2)

    @patch.object(pb.time, 'sleep')
    @patch.object(pb, 'http_download_once')
    def test_repeated_504_fails_after_three_attempts(self, download, sleep):
        download.side_effect = http_error(504)
        with self.assertRaises(urllib.error.HTTPError):
            pb.http_download('https://example.invalid/asset', Path('asset.zip'))
        self.assertEqual(download.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(pb.time, 'sleep')
    @patch.object(pb, 'http_download_once')
    def test_404_not_retried(self, download, sleep):
        download.side_effect = http_error(404)
        with self.assertRaises(urllib.error.HTTPError):
            pb.http_download('https://example.invalid/asset', Path('asset.zip'))
        self.assertEqual(download.call_count, 1)
        sleep.assert_not_called()


    @patch.object(pb.shutil, 'which', return_value=None)
    @patch.object(pb, 'http_download')
    def test_api_fallback_after_gateway_failure(self, download, _which):
        asset = 'bootstrap-arm.zip'
        api = 'https://api.github.com/repos/termux/termux-packages/releases/assets/123'
        content = b'example archive'
        def fake_download(url, dest):
            if url != api:
                raise http_error(504)
            dest.write_bytes(content)
        download.side_effect = fake_download
        with tempfile.TemporaryDirectory() as tmp, patch.dict(pb.ASSET_API_URLS, {asset: api}, clear=True), patch.dict('os.environ', {'REA_BOOTSTRAP_MIRROR': '', 'REA_BOOTSTRAP_PROXY': ''}):
            dest = Path(tmp) / asset
            pb.download('https://github.com/example/asset', dest,
                        hashlib.sha256(content).hexdigest(), 'release', asset)
            self.assertEqual(dest.read_bytes(), content)
            self.assertEqual(download.call_args_list[-1].args[0], api)

    @patch.object(pb.urllib.request, 'urlopen')
    def test_api_request_accepts_binary(self, urlopen):
        urlopen.side_effect = RuntimeError('stop before download')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                pb.http_download_once('https://api.github.com/repos/termux/termux-packages/releases/assets/123', Path(tmp) / 'asset.zip')
        self.assertEqual(urlopen.call_args.args[0].get_header('Accept'), 'application/octet-stream')

if __name__ == '__main__':
    unittest.main()
