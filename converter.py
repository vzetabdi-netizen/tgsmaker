"""
SVG / PNG to TGS Converter Module
Handles conversion from SVG or PNG files to TGS (Telegram Sticker) format using python-lottie.

Supported inputs:
  - SVG  : any valid SVG (should be 512x512)
  - PNG  : any PNG (minimum 100x100 px); automatically upscaled to 512x512 and
           wrapped in a Lottie JSON before being compressed to TGS.
"""

import os
import json
import gzip
import shutil
import struct
import subprocess
import tempfile
import logging
import asyncio
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_png_dimensions(png_path: str) -> tuple[int, int]:
    """
    Read width and height from a PNG file without external libraries.
    PNG spec: bytes 16-23 of the file contain IHDR width (4 bytes) + height (4 bytes).
    """
    with open(png_path, 'rb') as f:
        sig = f.read(8)
        if sig != b'\x89PNG\r\n\x1a\n':
            raise ValueError("Not a valid PNG file.")
        f.read(4)   # chunk length
        chunk = f.read(4)
        if chunk != b'IHDR':
            raise ValueError("PNG missing IHDR chunk.")
        width  = struct.unpack('>I', f.read(4))[0]
        height = struct.unpack('>I', f.read(4))[0]
    return width, height


def _png_to_lottie_json(png_path: str, target_size: int = 512) -> str:
    """
    Embed a PNG as a base64 image asset inside a minimal Lottie JSON,
    then save it as a temporary .json file and return its path.

    The animation is a single still frame (1 frame, 30 fps) with the PNG
    stretched to target_size × target_size.
    """
    import base64

    with open(png_path, 'rb') as f:
        png_b64 = base64.b64encode(f.read()).decode('ascii')

    lottie = {
        "v": "5.5.7",
        "fr": 30,
        "ip": 0,
        "op": 1,
        "w": target_size,
        "h": target_size,
        "nm": "sticker",
        "ddd": 0,
        "assets": [
            {
                "id": "img_0",
                "w": target_size,
                "h": target_size,
                "u": "",
                "p": f"data:image/png;base64,{png_b64}",
                "e": 1
            }
        ],
        "layers": [
            {
                "ddd": 0,
                "ind": 1,
                "ty": 2,          # image layer
                "nm": "image",
                "refId": "img_0",
                "sr": 1,
                "ks": {
                    "o":  {"a": 0, "k": 100},
                    "r":  {"a": 0, "k": 0},
                    "p":  {"a": 0, "k": [target_size / 2, target_size / 2, 0]},
                    "a":  {"a": 0, "k": [target_size / 2, target_size / 2, 0]},
                    "s":  {"a": 0, "k": [100, 100, 100]}
                },
                "ao": 0,
                "ip": 0,
                "op": 1,
                "st": 0,
                "bm": 0
            }
        ]
    }

    fd, json_path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w') as jf:
        json.dump(lottie, jf)

    return json_path


def _json_to_tgs(json_path: str) -> str:
    """Gzip-compress a Lottie JSON file to produce a .tgs file."""
    fd, tgs_path = tempfile.mkstemp(suffix='.tgs')
    os.close(fd)

    with open(json_path, 'rb') as f_in, gzip.open(tgs_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)

    return tgs_path


# ---------------------------------------------------------------------------
# Main converter class
# ---------------------------------------------------------------------------

class SVGToTGSConverter:
    def __init__(self):
        self.lottie_convert_path = self._find_lottie_convert()

    def _find_lottie_convert(self) -> str:
        """Find the lottie_convert.py executable."""
        possible_paths = [
            'lottie_convert.py',
            '/usr/local/bin/lottie_convert.py',
            '/usr/bin/lottie_convert.py',
            os.path.expanduser('~/.local/bin/lottie_convert.py'),
        ]

        for path in possible_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                logger.info(f"Found lottie_convert.py at: {path}")
                return path

        try:
            result = subprocess.run(
                ['which', 'lottie_convert.py'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                logger.info(f"Found lottie_convert.py in PATH: {path}")
                return path
        except Exception:
            pass

        logger.warning("lottie_convert.py not found; will try it directly.")
        return 'lottie_convert.py'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def convert(self, input_path: str) -> str:
        """
        Convert an SVG or PNG file to TGS format.

        Args:
            input_path: Path to the input file (.svg or .png).

        Returns:
            Path to the generated .tgs file.

        Raises:
            ValueError: For unsupported file types or invalid PNG size.
            Exception:  For conversion failures.
        """
        ext = Path(input_path).suffix.lower()

        if ext == '.svg':
            return await self._convert_svg(input_path)
        elif ext == '.png':
            return await self._convert_png(input_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}. Only .svg and .png are supported.")

    # ------------------------------------------------------------------
    # SVG conversion
    # ------------------------------------------------------------------

    async def _convert_svg(self, svg_path: str) -> str:
        """Convert SVG → TGS via lottie_convert.py."""
        tgs_fd, tgs_path = tempfile.mkstemp(suffix='.tgs')
        os.close(tgs_fd)

        try:
            # lottie_convert.py only needs: input output
            # Extra flags like --optimize / --fps / --width are NOT supported
            # by all versions; keep the command minimal and safe.
            cmd = [
                self.lottie_convert_path,
                svg_path,
                tgs_path,
            ]

            logger.info(f"Running SVG conversion: {' '.join(cmd)}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                err = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
                logger.error(f"lottie_convert.py failed (code {process.returncode}): {err}")
                raise Exception(f"SVG conversion failed: {err}")

            if not os.path.exists(tgs_path) or os.path.getsize(tgs_path) == 0:
                raise Exception("Conversion produced an empty TGS file.")

            file_size = os.path.getsize(tgs_path)
            if file_size > 64 * 1024:
                logger.warning(
                    f"TGS file is {file_size} bytes — exceeds Telegram's 64 KB limit."
                )

            logger.info(f"SVG → TGS done: {tgs_path} ({file_size} bytes)")
            return tgs_path

        except Exception:
            if os.path.exists(tgs_path):
                os.unlink(tgs_path)
            raise

    # ------------------------------------------------------------------
    # PNG conversion
    # ------------------------------------------------------------------

    async def _convert_png(self, png_path: str) -> str:
        """
        Convert PNG → TGS.

        Steps:
          1. Validate PNG dimensions (≥ 100 × 100 px).
          2. Build a minimal Lottie JSON that embeds the PNG as a base64 asset.
          3. Gzip the JSON to produce the .tgs file.
        """
        # Step 1 – validate dimensions
        try:
            width, height = _read_png_dimensions(png_path)
        except Exception as e:
            raise ValueError(f"Cannot read PNG dimensions: {e}")

        if width < 100 or height < 100:
            raise ValueError(
                f"PNG must be at least 100×100 pixels. "
                f"Your file is {width}×{height} pixels."
            )

        logger.info(f"Converting PNG ({width}×{height}) → TGS")

        # Step 2 – build Lottie JSON (runs fast; no need for a subprocess)
        json_path = None
        try:
            json_path = await asyncio.to_thread(_png_to_lottie_json, png_path)

            # Step 3 – gzip → .tgs
            tgs_path = await asyncio.to_thread(_json_to_tgs, json_path)

        finally:
            if json_path and os.path.exists(json_path):
                os.unlink(json_path)

        file_size = os.path.getsize(tgs_path)
        if file_size > 64 * 1024:
            logger.warning(
                f"PNG-based TGS is {file_size} bytes — exceeds Telegram's 64 KB limit. "
                "Consider using a smaller or more compressed PNG."
            )

        logger.info(f"PNG → TGS done: {tgs_path} ({file_size} bytes)")
        return tgs_path

    # ------------------------------------------------------------------
    # Dependency check
    # ------------------------------------------------------------------

    def validate_dependencies(self) -> tuple[bool, str]:
        """Check that lottie_convert.py is available (needed for SVG only)."""
        try:
            result = subprocess.run(
                [self.lottie_convert_path, '--help'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode not in (0, 1):   # --help may exit 1 on some versions
                return False, f"lottie_convert.py not working: {result.stderr}"
            return True, "All dependencies are available."
        except subprocess.TimeoutExpired:
            return False, "lottie_convert.py is not responding."
        except FileNotFoundError:
            return False, "lottie_convert.py is not installed or not in PATH."
        except Exception as e:
            return False, f"Dependency check error: {str(e)}"
