import zlib

from palworld_save_tools.ooz_lib import OozLib
from palworld_save_tools.oodle_lib import OodleLib # to be deleted soon, after libooz stable

MAGIC_BYTES = [b"PlZ", b"PlM"]

def check_sav_format(sav_data: bytes) -> int:
    """
    Check SAV file format
    Returns: 1=PLM(Oodle), 0=PLZ(Zlib), -1=Unknown
    """
    if len(sav_data) < 24:
        return -1

    # Determine header offset
    header_offset = 12 if sav_data.startswith(b"CNK") else 0

    if len(sav_data) < header_offset + 11:
        return -1

    # Check magic bytes
    magic = sav_data[header_offset + 8 : header_offset + 11]

    if magic == b"PlM":
        return 1  # PLM format (Oodle)
    elif magic == b"PlZ":
        return 0  # PLZ format (Zlib)
    else:
        return -1  # Unknown format
        
def decompress_sav_to_gvas(data: bytes, zlib: bool = False) -> tuple[bytes, int]:
    format = check_sav_format(data)
    
    if format == 0:
        print("Using zlib decompression for Palworld save")
        return decompress_sav_to_gvas_with_zlib(data)
    elif format == 1:
        print("Using Oodle decompression for Palworld save")
        return OozLib().decompress_sav_to_gvas(data)
    elif format == -1:
        raise Exception("Unknown save format")

    print("Using Oodle decompression for Palworld save")


def decompress_sav_to_gvas_with_zlib(data: bytes) -> tuple[bytes, int]:
    uncompressed_len = int.from_bytes(data[0:4], byteorder="little")
    compressed_len = int.from_bytes(data[4:8], byteorder="little")
    magic_bytes = data[8:11]
    save_type = data[11]
    data_start_offset = 12
    # Check for magic bytes
    if magic_bytes == b"CNK":
        uncompressed_len = int.from_bytes(data[12:16], byteorder="little")
        compressed_len = int.from_bytes(data[16:20], byteorder="little")
        magic_bytes = data[20:23]
        save_type = data[23]
        data_start_offset = 24
    if magic_bytes not in MAGIC_BYTES:
        if (
            magic_bytes == b"\x00\x00\x00"
            and uncompressed_len == 0
            and compressed_len == 0
        ):
            raise Exception(
                f"not a compressed Palworld save, found too many null bytes, this is likely corrupted"
            )
        raise Exception(
            f"not a compressed Palworld save, found {magic_bytes!r} instead of {MAGIC_BYTES!r}"
        )
    # Valid save types
    if save_type not in [0x30, 0x31, 0x32]:
        raise Exception(f"unknown save type: {save_type}")
    # We only have 0x31 (single zlib) and 0x32 (double zlib) saves
    if save_type not in [0x31, 0x32]:
        raise Exception(f"unhandled compression type: {save_type}")
    if save_type == 0x31:
        # Check if the compressed length is correct
        if compressed_len != len(data) - data_start_offset:
            raise Exception(f"incorrect compressed length: {compressed_len}")
    # Decompress file
    uncompressed_data = zlib.decompress(data[data_start_offset:])
    if save_type == 0x32:
        # Check if the compressed length is correct
        if compressed_len != len(uncompressed_data):
            raise Exception(f"incorrect compressed length: {compressed_len}")
        # Decompress file
        uncompressed_data = zlib.decompress(uncompressed_data)
    # Check if the uncompressed length is correct
    if uncompressed_len != len(uncompressed_data):
        raise Exception(f"incorrect uncompressed length: {uncompressed_len}")

    return uncompressed_data, save_type

def compress_gvas_to_sav(data: bytes, save_type: int, zlib: bool = False) -> bytes:
    if zlib:
        print("Using zlib compression for Palworld save")
        return compress_gvas_to_sav_with_zlib(data, save_type)

    print("Using Oodle compression for Palworld save")
    return OozLib().compress_gvas_to_sav(data, save_type)

def compress_gvas_to_sav_with_zlib(data: bytes, save_type: int) -> bytes:
    uncompressed_len = len(data)
    compressed_data = zlib.compress(data)
    compressed_len = len(compressed_data)
    if save_type == 0x32:
        compressed_data = zlib.compress(compressed_data)

    # Create a byte array and append the necessary information
    result = bytearray()
    result.extend(uncompressed_len.to_bytes(4, byteorder="little"))
    result.extend(compressed_len.to_bytes(4, byteorder="little"))
    result.extend(MAGIC_BYTES[0])  # Use the first magic bytes
    result.extend(bytes([save_type]))
    result.extend(compressed_data)

    return bytes(result)
