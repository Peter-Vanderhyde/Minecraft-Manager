import struct
import zlib
import math
from pathlib import Path

def get_inhabited_time_fast(raw_nbt: bytes) -> int:
    TAG_UPPER = b'\x04\x00\rInhabitedTime'
    TAG_LOWER = b'\x04\x00\rinhabitedTime'
    idx = raw_nbt.find(TAG_UPPER)
    if idx == -1:
        idx = raw_nbt.find(TAG_LOWER)
    if idx == -1:
        return 0
    val_start = idx + len(TAG_UPPER)
    return struct.unpack(">q", raw_nbt[val_start : val_start + 8])[0]


def prune_and_defrag_mca(mca_path: str, min_inhabited_ticks: int = 1200):
    """
    Parses a .mca file, removes chunks with InhabitedTime < min_inhabited_ticks,
    and defragments the binary data to physically shrink the file size on disk.
    """
    mca_path = Path(mca_path)
    with open(mca_path, "rb") as f:
        old_data = f.read()

    if len(old_data) < 8192:
        return 0, 0, 0  # File corrupted or too small

    # 1. Initialize new MCA file buffers
    # First 4096 bytes: Location Header, Next 4096 bytes: Timestamp Header
    new_locations = bytearray(4096)
    new_timestamps = bytearray(4096)
    new_payload = bytearray()
    
    current_sector = 2  # Sectors 0 and 1 are reserved for the headers (8192 bytes / 4096)
    chunks_retained = 0
    chunks_deleted = 0

    # 2. Iterate through all 1024 chunks in the region
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
            compressed_chunk = old_data[offset : offset + 4 + payload_len]  # Full payload (len + type + compressed data)
            raw_compressed = old_data[offset + 5 : offset + 4 + payload_len]

            # Decompress and check InhabitedTime
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

            # 3. Decision: Keep or Discard
            if inhabited_ticks >= min_inhabited_ticks:
                # KEEP CHUNK: Append to the new compact payload buffer
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

    # 4. Write back the tightly packed defragmented file
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