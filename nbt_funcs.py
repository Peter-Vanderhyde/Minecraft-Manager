import struct
import zlib
import math
import re
from pathlib import Path

def get_inhabited_time_fast(raw_nbt: bytes) -> int:
    # Identifies the InhabitedTime tag within the raw NBT byte stream
    TAG_UPPER = b'\x04\x00\rInhabitedTime'
    TAG_LOWER = b'\x04\x00\rinhabitedTime'
    idx = raw_nbt.find(TAG_UPPER)
    if idx == -1:
        idx = raw_nbt.find(TAG_LOWER)
    if idx == -1:
        return 0
    val_start = idx + len(TAG_UPPER)
    return struct.unpack(">q", raw_nbt[val_start : val_start + 8])[0]

def get_region_coords(filename: str):
    """Extracts region X and Z coordinates from the filename."""
    match = re.search(r'r\.(-?\d+)\.(-?\d+)\.mca', filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0

def scan_mca_for_inhabited_chunks(mca_path: str, min_inhabited_ticks: int) -> set:
    """Reads the MCA file and returns a set of global chunk coordinates that meet the threshold."""
    mca_path = Path(mca_path)
    surviving = set()
    
    if not mca_path.exists():
        return surviving

    with open(mca_path, "rb") as f:
        old_data = f.read()

    # File corrupted or too small
    if len(old_data) < 8192: 
        return surviving

    # Get the region coordinates to convert local chunks to global chunks
    rx, rz = get_region_coords(mca_path.name)

    # Iterate through all 1024 chunks in the region
    for cz in range(32):
        for cx in range(32):
            header_index = 4 * (cx + cz * 32)
            offset_bytes = old_data[header_index : header_index + 3]
            sector_count = old_data[header_index + 3]
            
            # Skip if chunk is ungenerated/empty
            if sector_count == 0 or offset_bytes == b'\x00\x00\x00':
                continue
            
            offset = int.from_bytes(offset_bytes, byteorder="big") * 4096
            
            # Extract payload metadata
            payload_len = struct.unpack(">I", old_data[offset : offset + 4])[0]
            compression_type = old_data[offset + 4]
            raw_compressed = old_data[offset + 5 : offset + 4 + payload_len]

            # Decompress
            try:
                if compression_type == 2:  # Zlib
                    raw_nbt = zlib.decompress(raw_compressed)
                elif compression_type == 1:  # GZip
                    raw_nbt = zlib.decompress(raw_compressed, zlib.MAX_WBITS | 32)
                else:
                    continue
            except zlib.error:
                continue

            inhabited_ticks = get_inhabited_time_fast(raw_nbt)

            if inhabited_ticks >= min_inhabited_ticks:
                # Calculate global coordinates
                global_cx = rx * 32 + cx
                global_cz = rz * 32 + cz
                surviving.add((global_cx, global_cz))

    return surviving

def prune_and_defrag_mca_by_set(mca_path: str, keep_set: set):
    """Physically rebuilds the MCA file, retaining only chunks present in the keep_set."""
    mca_path = Path(mca_path)
    with open(mca_path, "rb") as f:
        old_data = f.read()

    if len(old_data) < 8192:
        return 0, 0, 0

    # Initialize new MCA file buffers
    # First 4096 bytes: Location Header, Next 4096 bytes: Timestamp Header
    new_locations = bytearray(4096)
    new_timestamps = bytearray(4096)
    new_payload = bytearray()
    
    current_sector = 2  # Sectors 0 and 1 are reserved for the headers
    chunks_retained = 0
    chunks_deleted = 0

    rx, rz = get_region_coords(mca_path.name)

    for cz in range(32):
        for cx in range(32):
            header_index = 4 * (cx + cz * 32)
            offset_bytes = old_data[header_index : header_index + 3]
            sector_count = old_data[header_index + 3]
            
            if sector_count == 0 or offset_bytes == b'\x00\x00\x00':
                continue
            
            global_cx = rx * 32 + cx
            global_cz = rz * 32 + cz

            offset = int.from_bytes(offset_bytes, byteorder="big") * 4096
            payload_len = struct.unpack(">I", old_data[offset : offset + 4])[0]
            
            # Full payload (len + type + compressed data)
            compressed_chunk = old_data[offset : offset + 4 + payload_len]

            # Check if this specific chunk's global coordinates are in the safe zone
            if (global_cx, global_cz) in keep_set:
                chunk_bytes = len(compressed_chunk)
                
                # Calculate padded size in 4096-byte sectors
                sectors_needed = math.ceil(chunk_bytes / 4096.0)
                padded_length = sectors_needed * 4096
                
                # Pad payload out to sector boundary with zeroes
                padded_chunk_data = compressed_chunk.ljust(padded_length, b'\x00')
                new_payload.extend(padded_chunk_data)

                # Write new Location Header entry (3-byte offset + 1-byte sector count)
                offset_3bytes = current_sector.to_bytes(3, byteorder="big")
                new_locations[header_index : header_index + 3] = offset_3bytes
                new_locations[header_index + 3] = sectors_needed

                # Copy original Timestamp Header entry
                old_ts_idx = 4096 + header_index
                new_timestamps[header_index : header_index + 4] = old_data[old_ts_idx : old_ts_idx + 4]

                # Update running sector index for the next chunk
                current_sector += sectors_needed
                chunks_retained += 1
            else:
                chunks_deleted += 1

    # Write back the tightly packed defragmented file
    if chunks_deleted > 0 or len(new_payload) == 0:
        # If all chunks in a region were deleted, you can delete the .mca file entirely!
        if chunks_retained == 0:
            mca_path.unlink()  # Deletes empty .mca file from disk
            return chunks_deleted, len(old_data), 0

        final_file_data = new_locations + new_timestamps + new_payload
        
        with open(mca_path, "wb") as f:
            f.write(final_file_data)
            
        return chunks_deleted, len(old_data), len(final_file_data)

    return 0, len(old_data), len(old_data)