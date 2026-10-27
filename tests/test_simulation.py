import unittest
from pathlib import Path
from core.config import AppConfig

class MockDriveFile:
    def __init__(self, file_id: str, name: str, size: int, timestamp: float):
        self.file_id = file_id
        self.name = name
        self.size = size
        self.timestamp = timestamp

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024)

class TestEvictionLogic(unittest.TestCase):
    def test_rolling_eviction(self):
        # 100 MB storage limit
        limit_bytes = 100 * 1024 * 1024

        cloud_files = [
            MockDriveFile("1", "clip1.mp4", 30 * 1024 * 1024, 1000),
            MockDriveFile("2", "clip2.mp4", 30 * 1024 * 1024, 2000),
            MockDriveFile("3", "clip3.mp4", 30 * 1024 * 1024, 3000),
        ]
        # Current size = 90 MB
        current_size = sum(f.size for f in cloud_files)
        self.assertEqual(current_size, 90 * 1024 * 1024)

        # Incoming new clip = 25 MB. 90 + 25 = 115 MB > 100 MB
        new_clip_size = 25 * 1024 * 1024

        evicted = []
        while cloud_files and (current_size + new_clip_size > limit_bytes):
            oldest = cloud_files.pop(0)
            current_size -= oldest.size
            evicted.append(oldest.name)

        # Oldest clip1 should be evicted (current size becomes 60 MB)
        self.assertEqual(evicted, ["clip1.mp4"])
        self.assertEqual(current_size, 60 * 1024 * 1024)

        # Add new clip
        cloud_files.append(MockDriveFile("4", "clip4.mp4", new_clip_size, 4000))
        current_size += new_clip_size
        self.assertEqual(current_size, 85 * 1024 * 1024)
        self.assertLessEqual(current_size, limit_bytes)
        self.assertEqual([f.name for f in cloud_files], ["clip2.mp4", "clip3.mp4", "clip4.mp4"])

if __name__ == "__main__":
    unittest.main()
