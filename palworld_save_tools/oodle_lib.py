import os
import sys
import struct
import ctypes
import subprocess
import tempfile
from typing import Tuple

OODLE_COMPRESSOR_ID = 8 # kraken
OODLE_LEVEL = 4 # optimal

class OodleLib:
    """
    Class to handle Palworld save file operations.
    - Decompression is handled via a legally distributable, open-source
      Oodle implementation (libooz.dll).
    - Compression is not supported by this open-source library.
    """
    
    def __init__(self, dll_path: str = "libooz.dll", exe_path: str = "ooz.exe"):
        self.lib = self._load_oodle_library(dll_path)
        self._setup_oodle_functions()

    def _load_oodle_library(self, dll_path: str):
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

    def _setup_oodle_functions(self):
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

    def _parse_sav_header(self, sav_data: bytes) -> Tuple[int, int, bytes]:
        """Parse Palworld .sav file header."""
        if len(sav_data) < 12:
            raise ValueError("The .sav file is too small to parse.")
        uncompressed_len = struct.unpack('<I', sav_data[:4])[0]
        compressed_len = struct.unpack('<I', sav_data[4:8])[0]
        magic = sav_data[8:11]
        return uncompressed_len, compressed_len, magic

    def decompress_sav_to_gvas(self, sav_data: bytes) -> bytes:
        """
        Decodes .sav file using libooz.dll with correct buffer padding.
        """
        print("\nStarting decompression process with libooz.dll...")
        uncompressed_len, compressed_len, magic = self._parse_sav_header(sav_data)
        
        save_type = self.check_sav_format(sav_data)

        if magic != b"PlM":
            raise ValueError(f"Unsupported format or not Oodle. Magic: {magic}")
            
        print(f"Uncompressed Size: {uncompressed_len:,} bytes")
        
        oodle_raw_data = sav_data[12 : 12 + compressed_len]

        SAFE_SPACE_PADDING = 128
        buffer_size = uncompressed_len + SAFE_SPACE_PADDING
        decompressed_buffer = ctypes.create_string_buffer(buffer_size)
        
        print("Calling Ooz_Decompress...")
        result_size = self.lib.Ooz_Decompress(
            oodle_raw_data,
            len(oodle_raw_data),
            decompressed_buffer,
            buffer_size,
            0, 0, 0, None, 0, None, None, None, 0, 0
        )

        # =================================================================
        # IMPROVED CHECK LOGIC
        # =================================================================
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
        gvas_data = decompressed_buffer.raw[:uncompressed_len]
        
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
        print(f"Compressed stream magic bytes: {compressed_data[:8]}")

        # === Build .sav file header ===
        print("Building .sav file header...")
        header = bytearray()
        header.extend(src_len.to_bytes(4, "little"))
        header.extend(compressed_len.to_bytes(4, "little"))
        header.extend(b"PlM")
        header.append(save_type)

        final_sav_data = header + compressed_data
        print("Finished building .sav file.")
        return final_sav_data

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