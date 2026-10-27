import unittest
import time
from core.config import AppConfig

class MockClip:
    def __init__(self, name: str, size: int, timestamp: float):
        self.name = name
        self.size = size
        self.timestamp = timestamp

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024)

class TestTopKRecencySync(unittest.TestCase):
    def test_top_k_recency_and_retention(self):
        now = 1000000.0
        retention_days = 14
        cutoff = now - (retention_days * 86400)
        storage_limit_bytes = 100 * 1024 * 1024  # 100 MB limit

        # 4 clips:
        # clip1: 20 days old (outside retention) -> 30MB
        # clip2: 10 days old -> 40MB
        # clip3: 5 days old -> 40MB
        # clip4: 1 day old (newest) -> 40MB
        all_clips = [
            MockClip("clip1_old.mp4", 30 * 1024 * 1024, now - 20 * 86400),
            MockClip("clip2_mid.mp4", 40 * 1024 * 1024, now - 10 * 86400),
            MockClip("clip3_new.mp4", 40 * 1024 * 1024, now - 5 * 86400),
            MockClip("clip4_newest.mp4", 40 * 1024 * 1024, now - 1 * 86400),
        ]

        # 1. Retention filter: clip1 should be excluded
        eligible = [c for c in all_clips if c.timestamp >= cutoff]
        self.assertEqual([c.name for c in eligible], ["clip2_mid.mp4", "clip3_new.mp4", "clip4_newest.mp4"])

        # 2. Sort newest first
        eligible.sort(key=lambda c: c.timestamp, reverse=True)
        self.assertEqual([c.name for c in eligible], ["clip4_newest.mp4", "clip3_new.mp4", "clip2_mid.mp4"])

        # 3. Fit into 100 MB limit:
        # clip4 (40MB) + clip3 (40MB) = 80MB. clip2 (40MB) would be 120MB > 100MB, so clip2 is excluded!
        desired = []
        acc_bytes = 0
        for clip in eligible:
            if acc_bytes + clip.size <= storage_limit_bytes:
                desired.append(clip)
                acc_bytes += clip.size

        self.assertEqual([c.name for c in desired], ["clip4_newest.mp4", "clip3_new.mp4"])
        self.assertEqual(acc_bytes, 80 * 1024 * 1024)

        # 4. Now simulate Drive containing clip1, clip2, clip3:
        cloud_files = ["clip1_old.mp4", "clip2_mid.mp4", "clip3_new.mp4"]
        desired_names = {c.name for c in desired}

        to_delete = [name for name in cloud_files if name not in desired_names]
        to_upload = [c.name for c in desired if c.name not in cloud_files]

        # clip1 (too old) and clip2 (pushed out by clip4) must be deleted!
        self.assertEqual(to_delete, ["clip1_old.mp4", "clip2_mid.mp4"])
        # clip4 (newest) must be uploaded!
        self.assertEqual(to_upload, ["clip4_newest.mp4"])

        # 5. After delete and upload:
        new_cloud = ["clip3_new.mp4", "clip4_newest.mp4"]
        # Next run check:
        next_to_delete = [name for name in new_cloud if name not in desired_names]
        next_to_upload = [c.name for c in desired if c.name not in new_cloud]

        # Idempotent: 0 to delete, 0 to upload! NO LOOP POSSIBLE!
        self.assertEqual(next_to_delete, [])
        self.assertEqual(next_to_upload, [])

if __name__ == "__main__":
    unittest.main()
