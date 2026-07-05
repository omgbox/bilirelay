from __future__ import annotations

from typing import BinaryIO, Optional

from dashparse.mp4.boxes import read_box_header


class MP4Remuxer:
    def remux_to_fmp4(
        self,
        segments: list[bytes],
        output: BinaryIO,
    ) -> None:
        if not segments:
            return

        output.write(segments[0])

        for seg in segments[1:]:
            mv = memoryview(seg)
            offset = 0
            while offset < len(seg) - 8:
                header = read_box_header(mv, offset)
                if header.box_type in ("ftyp", "moov"):
                    offset += header.size
                    continue
                output.write(bytes(mv[header.offset : header.offset + header.size]))
                offset += header.size

    def remux_with_ffmpeg(
        self,
        video_segments: list[bytes],
        audio_segments: list[bytes],
        output_path: str,
    ) -> None:
        import subprocess
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            vpath = os.path.join(tmpdir, "video.mp4")
            apath = os.path.join(tmpdir, "audio.mp4")

            with open(vpath, "wb") as f:
                self.remux_to_fmp4(video_segments, f)
            with open(apath, "wb") as f:
                self.remux_to_fmp4(audio_segments, f)

            subprocess.run(
                [
                    "ffmpeg",
                    "-i", vpath,
                    "-i", apath,
                    "-c", "copy",
                    "-movflags", "faststart",
                    output_path,
                ],
                check=True,
                capture_output=True,
            )
