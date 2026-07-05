from __future__ import annotations

from dataclasses import dataclass, field

from dashparse.exceptions import SIDXParseError


@dataclass
class SidxReference:
    segment_duration: int
    referenced_size: int
    starts_with_sap: bool = True
    sap_type: int = 0
    sap_delta_time: int = 0


@dataclass
class SidxBox:
    version: int = 0
    flags: int = 0
    reference_id: int = 0
    timescale: int = 0
    earliest_presentation_time: int = 0
    first_offset: int = 0
    references: list[SidxReference] = field(default_factory=list)


    def encode(self) -> bytes:
        """Encode SidxBox to bytes."""
        import struct

        # Calculate total size
        ref_count = len(self.references)
        if self.version == 0:
            header_size = 8 + 4 + 4 + 4 + 4 + 4 + 2 + 2  # box header + version/flags + ref_id + timescale + ept + first_offset + reserved + ref_count
            ref_size = ref_count * 12  # each ref: size(4) + duration(4) + sap_flags(4)
        else:
            header_size = 8 + 4 + 4 + 4 + 8 + 8 + 2 + 2
            ref_size = ref_count * 12

        total_size = header_size + ref_size

        buf = bytearray(total_size)
        # Box header
        buf[0:4] = struct.pack(">I", total_size)
        buf[4:8] = b"sidx"
        # Version + flags
        buf[8] = self.version
        buf[9:12] = struct.pack(">I", self.flags)
        # Reference ID
        offset = 12
        struct.pack_into(">I", buf, offset, self.reference_id)
        offset += 4
        # Timescale
        struct.pack_into(">I", buf, offset, self.timescale)
        offset += 4

        if self.version == 0:
            struct.pack_into(">I", buf, offset, self.earliest_presentation_time)
            offset += 4
            struct.pack_into(">I", buf, offset, self.first_offset)
            offset += 4
        else:
            struct.pack_into(">Q", buf, offset, self.earliest_presentation_time)
            offset += 8
            struct.pack_into(">Q", buf, offset, self.first_offset)
            offset += 8

        # Reserved (2 bytes)
        struct.pack_into(">H", buf, offset, 0)
        offset += 2
        # Reference count
        struct.pack_into(">H", buf, offset, ref_count)
        offset += 2

        for ref in self.references:
            sap_flags = (
                (0x80000000 if ref.starts_with_sap else 0)
                | ((ref.sap_type & 0x7) << 28)
                | (ref.sap_delta_time & 0x0FFFFFFF)
            )
            struct.pack_into(">I", buf, offset, ref.referenced_size)
            offset += 4
            struct.pack_into(">I", buf, offset, ref.segment_duration)
            offset += 4
            struct.pack_into(">I", buf, offset, sap_flags)
            offset += 4

        return bytes(buf)


def parse_sidx(data: bytes) -> SidxBox:
    if len(data) < 8:
        raise SIDXParseError("Data too short for sidx box header")

    box_type = data[4:8].decode("ascii", errors="replace")
    if box_type != "sidx":
        raise SIDXParseError(f"Expected sidx box, got '{box_type}'")

    offset = 8
    version = data[offset]
    offset += 4  # version + flags

    reference_id = int.from_bytes(data[offset : offset + 4], "big")
    offset += 4
    timescale = int.from_bytes(data[offset : offset + 4], "big")
    offset += 4

    if version == 0:
        ept = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        first_offset = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
    else:
        ept = int.from_bytes(data[offset : offset + 8], "big")
        offset += 8
        first_offset = int.from_bytes(data[offset : offset + 8], "big")
        offset += 8

    offset += 2  # reserved
    ref_count = int.from_bytes(data[offset : offset + 2], "big")
    offset += 2

    refs = []
    for _ in range(ref_count):
        ref_size = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        duration = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        sap_flags = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        refs.append(
            SidxReference(
                referenced_size=ref_size,
                segment_duration=duration,
                starts_with_sap=bool(sap_flags & 0x80000000),
                sap_type=(sap_flags >> 28) & 0x7,
                sap_delta_time=sap_flags & 0x0FFFFFFF,
            )
        )

    return SidxBox(
        reference_id=reference_id,
        timescale=timescale,
        earliest_presentation_time=ept,
        first_offset=first_offset,
        references=refs,
    )
