import os
import sys
import struct
import ctypes
import subprocess
import tempfile
from typing import Tuple

OODLE_COMPRESSOR_ID = 8 # kraken
OODLE_LEVEL = 4 # optimal

class OozLib:
    """
    Class to handle Palworld save file operations.
    - Decompression is handled via a legally distributable, open-source
      Oodle implementation (libooz.dll).
    - Compression is not supported by this open-source library.
    """
    
    def __init__(self, dll_path: str = "libooz.dll", exe_path: str = "ooz.exe"):
        self.SAFE_SPACE_PADDING = 128  # Safe padding for decompression buffer
        self.lib = self._load_ooz_library(dll_path)
        self._setup_ooz_functions()

    def _load_ooz_library(self, dll_path: str):
        """Loads the libooz.dll library, ensuring dependencies can be found."""
        # Check in the script's directory if a full path isn't provided
        if not os.path.isabs(dll_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dll_path = os.path.join(
                script_dir, "libs", "ooz", dll_path
            )

        if not os.path.exists(dll_path):
            raise FileNotFoundError(
                f"FATAL: libooz.dll not found at '{dll_path}'.\n"
                "Please ensure you have placed libooz.dll (and its dependencies like libbun.dll) "
                "in the correct location."
            )
        
        try:
            # IMPORTANT: Add the DLL's directory to the search path
            # This helps Windows find other required DLLs like libbun.dll
            dll_directory = os.path.dirname(dll_path)
            os.add_dll_directory(dll_directory)

            print(f"Loading library from: {dll_path}")
            return ctypes.cdll.LoadLibrary(dll_path)
            
        except OSError as e:
            raise RuntimeError(f"Failed to load libooz.dll from '{dll_path}': {e}\n"
                               "This might be due to a missing dependency like 'Microsoft Visual C++ Redistributable'.")

    def _setup_ooz_functions(self):
        """Sets up the Ooz_Decompress function signature based on community findings."""
        self.lib.Ooz_Decompress.restype = ctypes.c_int
        self.lib.Ooz_Decompress.argtypes = [
            ctypes.c_void_p,   # src_buf
            ctypes.c_size_t,   # src_len
            ctypes.c_void_p,   # dst_buf
            ctypes.c_size_t,   # dst_size
            ctypes.c_int,      # fuzzSafe
            ctypes.c_int,      # checkCRC
            ctypes.c_int,      # verbosity
            ctypes.c_void_p,   # decBufBase
            ctypes.c_size_t,   # decBufSize
            ctypes.c_void_p,   # fpCallback
            ctypes.c_void_p,   # cbUserdata
            ctypes.c_void_p,   # scratch
            ctypes.c_size_t,   # scratchSize
            ctypes.c_int       # threadPhase
        ]
        
        self.lib.Ooz_Compress.restype = ctypes.c_int
        self.lib.Ooz_Compress.argtypes = [
            ctypes.c_int,        # compressor
            ctypes.c_void_p,     # src_buf
            ctypes.c_int,        # src_len
            ctypes.c_void_p,     # dst_buf
            ctypes.c_size_t,     # dst_capacity
            ctypes.c_int         # level
        ]
    
    def _parse_sav_header(self, sav_data: bytes) -> Tuple[int, int, bytes, int, int]:
        """
        Parse SAV file header
        Returns: (uncompressed length, compressed length, magic bytes, save type, data offset)
        """
        if len(sav_data) < 24:
            raise ValueError("File too small to parse header")

        # Determine header offset and data offset
        if sav_data.startswith(b"CNK"):
            header_offset = 12
            data_offset = 24
        else:
            header_offset = 0
            data_offset = 12

        # Parse header fields
        uncompressed_len = struct.unpack(
            "<I", sav_data[header_offset : header_offset + 4]
        )[0]
        compressed_len = struct.unpack(
            "<I", sav_data[header_offset + 4 : header_offset + 8]
        )[0]
        magic = sav_data[header_offset + 8 : header_offset + 11]
        save_type = sav_data[header_offset + 11]

        return uncompressed_len, compressed_len, magic, save_type, data_offset

    def check_sav_format(self, sav_data: bytes) -> int:
        """
        Check SAV file format.
        Returns: 1=PLM(Oodle), 0=PLZ(Zlib), -1=Unknown.
        (This method is preserved)
        """
        if len(sav_data) < 12:
            return -1
        magic = sav_data[8:11]
        print(f"Checking SAV format, magic bytes: {magic!r}")
        if magic == b"PlM":
            return 1
        elif magic == b"PlZ":
            return 0
        else:
            return -1

    def check_sav_format(self, sav_data: bytes) -> int:
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

    def decompress_sav_to_gvas(self, sav_data: bytes) -> bytes:
        """
        Decodes .sav file using libooz.dll with correct buffer padding.
        """
        print("\nStarting decompression process with libooz.dll...")
        
        if not sav_data:
            raise ValueError("SAV data cannot be empty")

        format_result = self.check_sav_format(sav_data)
        if format_result == 0:
            raise ValueError(
                "Detected PLZ format (Zlib), this tool only supports PLM format (Oodle)"
            )
        elif format_result == -1:
            raise ValueError("Unknown SAV file format")

        print("Detected PLM format (Oodle), starting decompression...")

        uncompressed_len, compressed_len, magic, save_type, data_offset = (
            self._parse_sav_header(sav_data)
        )

        print(f"File information:")
        print(f"  Magic bytes: {magic.decode('ascii', errors='ignore')}")
        print(f"  Save type: 0x{save_type:02X}")
        print(f"  Compressed size: {compressed_len:,} bytes")
        print(f"  Uncompressed size: {uncompressed_len:,} bytes")
        print(f"  Data offset: {data_offset} bytes")
        
        if len(sav_data) < data_offset + compressed_len:
            raise ValueError(
                f"File data is incomplete, expected {data_offset + compressed_len} bytes, actual {len(sav_data)} bytes"
            )
            
        compressed_data = sav_data[data_offset : data_offset + compressed_len]
        gvas_buffer = ctypes.create_string_buffer(uncompressed_len + self.SAFE_SPACE_PADDING)

        print("Calling Ooz_Decompress...")
        result_size = self.lib.Ooz_Decompress(
            compressed_data,
            compressed_len,
            gvas_buffer,
            uncompressed_len,
            0, 0, 0, None, 0, None, None, None, 0, 0
        )


        # Check for error (negative value)
        if result_size < 0:
            raise RuntimeError(f"Oodle decompression failed with error code: {result_size}")

        # Check if the result is at least as large as expected
        if result_size < uncompressed_len:
            raise RuntimeError(
                f"Decompressed size is smaller than expected. "
                f"Expected at least {uncompressed_len}, got {result_size}"
            )
        
        print(f"Ooz_Decompress function reported writing {result_size} bytes (including padding).")
        # =================================================================
        
        # Slice the result to get clean GVAS data (this is correct)
        gvas_data = gvas_buffer.raw[:uncompressed_len]
        
        print("Decompression successful!")
        return gvas_data, save_type

    def compress_gvas_to_sav(self, gvas_data: bytes, save_type: int) -> bytes:
        """
        Compresses GVAS data using libooz.dll (Ooz_Compress).
        """
        print("\nStarting compression process with libooz.dll (memory method)...")

        src_len = len(gvas_data)
        if src_len == 0:
            raise ValueError("Input data for compression must not be empty.")

        # === Prepare source and destination buffers ===
        src_buf = ctypes.create_string_buffer(gvas_data)
        dst_capacity = src_len * 2  # safe margin
        dst_buf = ctypes.create_string_buffer(dst_capacity)

        # === Call Ooz_Compress ===
        print("Calling Ooz_Compress...")
        result = self.lib.Ooz_Compress(
            OODLE_COMPRESSOR_ID,  # e.g. 8 for Kraken
            ctypes.cast(src_buf, ctypes.c_void_p),
            src_len,
            ctypes.cast(dst_buf, ctypes.c_void_p),
            dst_capacity,
            OODLE_LEVEL           # compression level, e.g. 4
        )

        if result <= 0:
            raise RuntimeError(f"Ooz_Compress failed or returned empty result (code: {result})")

        compressed_data = dst_buf.raw[:result]
        compressed_len = len(compressed_data)

        print(f"Compression successful, compressed size: {compressed_len:,} bytes")

        # === Build .sav file header ===
        print("Building .sav file...")
        result = bytearray()
        result.extend(src_len.to_bytes(4, "little"))
        result.extend(compressed_len.to_bytes(4, "little"))
        result.extend(b"PlM")
        result.extend(bytes([save_type]))
        result.extend(compressed_data)

        print("Finished building .sav file.")
        return bytes(result)

# =============================================================
# MAIN BLOCK FOR TESTING PURPOSES ONLY
# =============================================================
def main():
    """Example main function for testing decompression."""
    if len(sys.argv) != 3:
        print("A tool to decompress Palworld .sav files using the open-source libooz library.")
        print("\nUsage:")
        print("  Decompress: python your_script_name.py <input.sav> <output.gvas>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    if not os.path.exists(input_file):
        print(f"Error: input file not found: {input_file}")
        sys.exit(1)
        
    try:
        # Create an instance of the handler. It will find libooz.dll in the same folder.
        handler = OodleLib()
        
        with open(input_file, "rb") as f_in:
            data = f_in.read()

        gvas_data, save_type = handler.decompress_sav_to_gvas(data)
        
        with open(output_file, "wb") as f_out:
            f_out.write(gvas_data)
        
        print(f"\nSuccess! Decompressed GVAS file saved to {output_file}")
        print(f"Save Type: 0x{save_type:02X}")

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()