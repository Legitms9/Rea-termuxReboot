#!/usr/bin/env python3
"""Offline tests for transient HTTP failures during bootstrap downloads."""
import sys
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


if __name__ == '__main__':
    unittest.main()
