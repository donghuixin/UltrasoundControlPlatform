# -*- coding: utf-8 -*-
from __future__ import print_function

import imp
import os
import shutil
import tempfile
import threading
import time
import unittest


MODULE_PATH = os.path.join(
    os.path.dirname(__file__), "tx7316_hsdc_batch_capture.py"
)
capture = imp.load_source("tx7316_hsdc_batch_capture_under_test", MODULE_PATH)


class HsdcSaveCompletionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(
            prefix="hsdc_save_test_", dir=os.path.dirname(__file__)
        )

    def tearDown(self):
        shutil.rmtree(self.directory)

    def test_accepts_exact_stable_closed_file(self):
        path = os.path.join(self.directory, "complete.bin")
        with open(path, "wb") as handle:
            handle.write(b"x" * 128)
        self.assertTrue(capture.wait_for_completed_file(
            path, 128, timeout_seconds=0.5,
            stable_seconds=0.03, poll_seconds=0.01,
        ))

    def test_waits_for_background_writer(self):
        path = os.path.join(self.directory, "background.bin")

        def writer():
            with open(path, "wb") as handle:
                handle.write(b"x" * 64)
                handle.flush()
                os.fsync(handle.fileno())
                time.sleep(0.08)
                handle.write(b"y" * 64)

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            self.assertTrue(capture.wait_for_completed_file(
                path, 128, timeout_seconds=1.0,
                stable_seconds=0.03, poll_seconds=0.01,
            ))
        finally:
            thread.join()

    def test_rejects_missing_or_wrong_length_file(self):
        path = os.path.join(self.directory, "short.bin")
        with open(path, "wb") as handle:
            handle.write(b"x" * 64)
        self.assertFalse(capture.wait_for_completed_file(
            path, 128, timeout_seconds=0.08,
            stable_seconds=0.02, poll_seconds=0.01,
        ))


if __name__ == "__main__":
    unittest.main()
