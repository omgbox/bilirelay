from __future__ import annotations

from dashparse.demux.frame import Frame
from dashparse.models.segment import SegmentSequence
from dashparse.mp4.boxes import read_box_header


class MP4Demuxer:
    def demux(self, init_data: bytes, media_data: bytes) -> list[Frame]:
        frames: list[Frame] = []
        media_boxes = self._parse_top_level(media_data)

        moof_list = media_boxes.get("moof")
        mdat_list = media_boxes.get("mdat")
        if not moof_list or not mdat_list:
            return frames

        moof = moof_list[0]
        mdat = mdat_list[0]

        # Calculate moof offset within media_data for traf slicing
        moof_offset = 0
        mv = memoryview(media_data)
        while moof_offset < len(media_data) - 8:
            header = read_box_header(mv, moof_offset)
            if header.box_type == "moof":
                break
            moof_offset += header.size

        # Pass moof content (skip moof box header) to _parse_moof
        moof_content = moof[8:]
        trun_entries = self._parse_moof(moof_content)
        mdat_data_start = 8  # skip mdat box header
        offset = 0
        for entry in trun_entries:
            sample_size = entry["sample_size"]
            sample_data = mdat[mdat_data_start + offset : mdat_data_start + offset + sample_size]
            frames.append(
                Frame(
                    track_id=entry.get("track_id", 0),
                    data=bytes(sample_data),
                    timestamp=entry.get("timestamp", 0.0),
                    duration=entry.get("duration", 0.0),
                    is_keyframe=entry.get("is_keyframe", False),
                    composition_time_offset=entry.get("composition_time_offset", 0.0),
                )
            )
            offset += sample_size

        return frames

    def demux_all(self, segment: SegmentSequence) -> list[Frame]:
        frames: list[Frame] = []
        if segment.init_segment and segment.init_segment.media_data:
            init_data = segment.init_segment.media_data
        else:
            return frames
        for seg in segment.media_segments:
            if seg.media_data:
                frames.extend(self.demux(init_data, seg.media_data))
        return frames

    def _parse_top_level(self, data: bytes) -> dict[str, list[memoryview]]:
        boxes: dict[str, list[memoryview]] = {}
        mv = memoryview(data)
        offset = 0
        while offset < len(data) - 8:
            header = read_box_header(mv, offset)
            box_type = header.box_type
            if box_type not in boxes:
                boxes[box_type] = []
            boxes[box_type].append(mv[header.offset : header.offset + header.size])
            offset += header.size
        return boxes

    def _parse_moof(self, moof_content: memoryview) -> list[dict]:
        entries: list[dict] = []
        offset = 0
        while offset < len(moof_content) - 8:
            header = read_box_header(moof_content, offset)
            if header.box_type == "traf":
                # Pass the full traf box (with header) so _parse_traf can read tfhd/tfdt/trun
                traf_box = moof_content[offset : offset + header.size]
                entries.extend(self._parse_traf(traf_box))
            offset += header.size
        return entries

    def _parse_traf(self, traf_data: memoryview) -> list[dict]:
        entries: list[dict] = []
        # Skip traf box header (8 bytes)
        offset = 8
        tfhd: dict = {}
        tfdt: dict = {}
        while offset < len(traf_data) - 8:
            header = read_box_header(traf_data, offset)
            if header.box_type == "tfhd":
                tfhd = self._parse_tfhd(traf_data[header.data_offset : header.offset + header.size])
            elif header.box_type == "tfdt":
                tfdt = self._parse_tfdt(traf_data[header.data_offset : header.offset + header.size])
            elif header.box_type == "trun":
                entries.extend(
                    self._parse_trun(
                        traf_data[header.data_offset : header.offset + header.size],
                        tfhd,
                        tfdt,
                    )
                )
            offset += header.size
        return entries

    def _parse_tfhd(self, data: memoryview) -> dict:
        if len(data) < 8:
            return {}
        offset = 4  # version + flags
        track_id = int.from_bytes(data[offset : offset + 4], "big")
        return {"track_id": track_id}

    def _parse_tfdt(self, data: memoryview) -> dict:
        if len(data) < 8:
            return {}
        version = data[0]
        offset = 4
        if version == 0:
            base_decode_time = int.from_bytes(data[offset : offset + 4], "big")
        else:
            base_decode_time = int.from_bytes(data[offset : offset + 8], "big")
        return {"base_decode_time": base_decode_time}

    def _parse_trun(self, data: memoryview, tfhd: dict, tfdt: dict) -> list[dict]:
        entries: list[dict] = []
        if len(data) < 8:
            return entries
        version = data[0]
        flags = int.from_bytes(data[1:4], "big")
        offset = 4
        sample_count = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4

        has_data_offset = bool(flags & 0x000001)
        has_sample_duration = bool(flags & 0x000100)
        has_sample_size = bool(flags & 0x000200)
        has_sample_flags = bool(flags & 0x000004)
        has_sample_cts = bool(flags & 0x000008)

        data_offset = 0
        if has_data_offset:
            data_offset = int.from_bytes(data[offset : offset + 4], "big", signed=True)
            offset += 4

        base_time = tfdt.get("base_decode_time", 0)
        current_time = base_time
        track_id = tfhd.get("track_id", 0)

        for i in range(sample_count):
            sample = {"track_id": track_id}

            if has_sample_duration:
                sample["duration"] = int.from_bytes(data[offset : offset + 4], "big")
                offset += 4
            else:
                sample["duration"] = 0

            if has_sample_size:
                sample["sample_size"] = int.from_bytes(data[offset : offset + 4], "big")
                offset += 4
            else:
                sample["sample_size"] = 0

            if has_sample_flags:
                flags_val = int.from_bytes(data[offset : offset + 4], "big")
                sample["is_keyframe"] = not bool(flags_val & 0x01000000)
                offset += 4
            else:
                sample["is_keyframe"] = True

            if has_sample_cts:
                cts = int.from_bytes(data[offset : offset + 4], "big", signed=True)
                sample["composition_time_offset"] = cts
                offset += 4
            else:
                sample["composition_time_offset"] = 0

            sample["timestamp"] = current_time
            current_time += sample["duration"]
            entries.append(sample)

        return entries
