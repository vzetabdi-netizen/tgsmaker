"""
SVG → TGS Converter Module
Converts SVG files to TGS (Telegram Sticker) format.

Speed strategy:
  - Uses python-lottie API directly (no subprocess) → no per-file Python startup cost
  - lottie library is imported ONCE at module load and reused for every conversion
  - Falls back to subprocess if direct import fails
"""

import os
import gzip
import json
import shutil
import subprocess
import tempfile
import logging
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import lottie library once at startup
# ---------------------------------------------------------------------------
try:
    import lottie
    from lottie.parsers.svg import parse_svg_file
    from lottie.exporters.core import export_tgs
    _LOTTIE_AVAILABLE = True
    logger.info("lottie library loaded — using fast in-process conversion")
except Exception as e:
    _LOTTIE_AVAILABLE = False
    logger.warning(f"lottie import failed ({e}), will fall back to subprocess")


# ---------------------------------------------------------------------------
# In-process conversion (fast — no subprocess startup)
# ---------------------------------------------------------------------------

def _svg_to_tgs_inprocess(svg_path: str) -> str:
    """
    Convert SVG → TGS fully in-process using the lottie Python API.
    No subprocess is spawned — reuses the already-loaded lottie module.
    Returns the path to the resulting .tgs temp file.
    """
    anim = parse_svg_file(svg_path)

    fd, tgs_path = tempfile.mkstemp(suffix='.tgs')
    os.close(fd)

    with open(tgs_path, 'wb') as f:
        export_tgs(anim, f)

    return tgs_path


# ---------------------------------------------------------------------------
# Subprocess fallback (slower — starts a new Python process each time)
# ---------------------------------------------------------------------------

def _find_lottie_convert() -> str:
    possible = [
        'lottie_convert.py',
        '/usr/local/bin/lottie_convert.py',
        '/usr/bin/lottie_convert.py',
        os.path.expanduser('~/.local/bin/lottie_convert.py'),
    ]
    for p in possible:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    try:
        r = subprocess.run(['which', 'lottie_convert.py'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return 'lottie_convert.py'


_LOTTIE_CONVERT_PATH: str = _find_lottie_convert()


def _svg_to_tgs_subprocess(svg_path: str) -> str:
    """Fallback: spawn lottie_convert.py as a subprocess."""
    fd, tgs_path = tempfile.mkstemp(suffix='.tgs')
    os.close(fd)
    try:
        result = subprocess.run(
            [_LOTTIE_CONVERT_PATH, svg_path, tgs_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise Exception(f"lottie_convert.py failed: {result.stderr}")
        if not os.path.exists(tgs_path) or os.path.getsize(tgs_path) == 0:
            raise Exception("Conversion produced an empty TGS file.")
        return tgs_path
    except Exception:
        if os.path.exists(tgs_path):
            os.unlink(tgs_path)
        raise


# ---------------------------------------------------------------------------
# Main converter class
# ---------------------------------------------------------------------------

class SVGToTGSConverter:
    """
    Converts SVG files to TGS format as fast as possible.

    Priority:
      1. In-process lottie API  → fastest (no subprocess)
      2. lottie_convert.py subprocess → fallback
    """

    async def convert(self, input_path: str) -> str:
        """
        Convert an SVG file to TGS.  Returns path to the .tgs temp file.
        Runs the CPU-bound work in a thread so the event loop stays free.
        """
        ext = Path(input_path).suffix.lower()
        if ext != '.svg':
            raise ValueError(f"Unsupported file type: {ext}. Only .svg is supported.")

        return await asyncio.to_thread(self._convert_sync, input_path)

    def _convert_sync(self, svg_path: str) -> str:
        """Synchronous conversion — called from a thread."""
        if _LOTTIE_AVAILABLE:
            try:
                tgs_path = _svg_to_tgs_inprocess(svg_path)
                size = os.path.getsize(tgs_path)
                if size == 0:
                    raise Exception("In-process conversion produced empty file.")
                logger.info(f"SVG → TGS (in-process): {size} bytes")
                if size > 64 * 1024:
                    logger.warning(f"TGS {size}B > 64 KB Telegram limit")
                return tgs_path
            except Exception as e:
                logger.warning(f"In-process conversion failed ({e}), trying subprocess…")

        # Fallback
        tgs_path = _svg_to_tgs_subprocess(svg_path)
        size = os.path.getsize(tgs_path)
        logger.info(f"SVG → TGS (subprocess fallback): {size} bytes")
        if size > 64 * 1024:
            logger.warning(f"TGS {size}B > 64 KB Telegram limit")
        return tgs_path

    def validate_dependencies(self) -> tuple[bool, str]:
        if _LOTTIE_AVAILABLE:
            return True, "lottie library available (in-process, fast)."
        try:
            r = subprocess.run([_LOTTIE_CONVERT_PATH, '--help'],
                               capture_output=True, text=True, timeout=10)
            if r.returncode in (0, 1):
                return True, "lottie_convert.py available (subprocess fallback)."
            return False, f"lottie_convert.py not working: {r.stderr}"
        except FileNotFoundError:
            return False, "Neither lottie library nor lottie_convert.py found."
        except Exception as e:
            return False, f"Dependency check error: {e}"
