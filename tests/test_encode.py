from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from slashdigitize.video.encode import prepare_inputs_for_timelapse, write_concat_file


class TimelapseTemporaryPathTests(unittest.TestCase):
    def test_concat_file_is_created_in_requested_output_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="slashmad-test-") as root:
            output_dir = Path(root) / "2026-09-11 Bergudden Holmön"
            output_dir.mkdir()
            image_path = output_dir / "_DSC8861.png"

            concat_path = Path(
                write_concat_file([str(image_path)], 25.0, directory=str(output_dir))
            )
            try:
                self.assertEqual(concat_path.parent, output_dir)
                contents = concat_path.read_text(encoding="utf-8")
                self.assertIn(f"file '{image_path}'", contents)
            finally:
                concat_path.unlink(missing_ok=True)

    def test_raw_previews_are_created_in_requested_output_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="slashmad-test-") as root:
            output_dir = Path(root) / "2026-09-11 Bergudden Holmön"
            output_dir.mkdir()
            raw_path = Path(root) / "frame.arw"
            raw_path.write_bytes(b"header\xff\xd8\xffpreview\xff\xd9tail")

            prepared = prepare_inputs_for_timelapse(
                [str(raw_path)],
                temp_parent=str(output_dir),
            )
            self.assertIsNotNone(prepared.temp_dir)
            preview_dir = Path(prepared.temp_dir or "")
            try:
                self.assertEqual(preview_dir.parent, output_dir)
                self.assertEqual(len(prepared.paths), 1)
                self.assertTrue(Path(prepared.paths[0]).is_file())
            finally:
                shutil.rmtree(preview_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
