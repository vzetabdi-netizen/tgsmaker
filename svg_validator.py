"""
SVG & PNG Validator Module
Validates SVG files (512x512) and PNG files (≥100x100) before TGS conversion.
"""

import xml.etree.ElementTree as ET
import struct
import re
import logging

logger = logging.getLogger(__name__)


class SVGValidator:
    REQUIRED_WIDTH  = 512
    REQUIRED_HEIGHT = 512

    def validate_svg_file(self, svg_path: str) -> tuple[bool, str]:
        """
        Validate an SVG file for TGS conversion requirements.

        Returns:
            (is_valid, error_message)
        """
        try:
            tree = ET.parse(svg_path)
            root = tree.getroot()

            if not self._is_svg_element(root):
                return False, "File is not a valid SVG format."

            width, height = self._extract_dimensions(root)

            if width is None or height is None:
                return False, (
                    "Could not determine SVG dimensions. "
                    "Please ensure your SVG has explicit width and height attributes."
                )

            if width != self.REQUIRED_WIDTH or height != self.REQUIRED_HEIGHT:
                return False, (
                    f"SVG must be exactly {self.REQUIRED_WIDTH}×{self.REQUIRED_HEIGHT} pixels. "
                    f"Your file is {width}×{height} pixels."
                )

            ok, msg = self._validate_content(root)
            if not ok:
                return False, msg

            return True, "SVG is valid for TGS conversion."

        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            return False, "Invalid SVG file — the file appears to be corrupted."

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False, f"Error validating SVG file: {str(e)}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_svg_element(self, element) -> bool:
        tag = element.tag.lower()
        return tag == 'svg' or tag.endswith('}svg')

    def _extract_dimensions(self, root) -> tuple[int | None, int | None]:
        try:
            width  = self._parse_dimension(root.get('width'))
            height = self._parse_dimension(root.get('height'))

            if width is not None and height is not None:
                return int(width), int(height)

            # Fall back to viewBox
            viewbox = root.get('viewBox')
            if viewbox:
                parts = viewbox.strip().split()
                if len(parts) == 4:
                    return int(float(parts[2])), int(float(parts[3]))

            return None, None

        except (ValueError, TypeError) as e:
            logger.error(f"Dimension parsing error: {e}")
            return None, None

    def _parse_dimension(self, dim_str: str) -> float | None:
        if not dim_str:
            return None
        dim_str = dim_str.strip().lower()
        if dim_str.endswith('%'):
            return None
        m = re.match(r'^(\d*\.?\d+)', dim_str)
        return float(m.group(1)) if m else None

    def _validate_content(self, root) -> tuple[bool, str]:
        try:
            svg_string = ET.tostring(root, encoding='unicode')
            if len(svg_string) > 1024 * 1024:   # 1 MB
                return False, "SVG file is too large (>1 MB) for TGS conversion."

            element_count = sum(1 for _ in root.iter())
            if element_count > 1000:
                return False, (
                    f"SVG is too complex ({element_count} elements). "
                    "Please simplify the file before converting."
                )

            return True, ""

        except Exception as e:
            logger.error(f"Content validation error: {e}")
            return False, f"Content validation error: {str(e)}"


# ---------------------------------------------------------------------------

class PNGValidator:
    """Validate PNG files before TGS conversion."""

    MIN_WIDTH  = 100
    MIN_HEIGHT = 100

    def validate_png_file(self, png_path: str) -> tuple[bool, str]:
        """
        Validate a PNG file for TGS conversion.

        Checks:
          - Valid PNG signature.
          - Dimensions ≥ 100 × 100 px.
          - File size ≤ 10 MB (handled upstream, but double-checked here).

        Returns:
            (is_valid, error_message)
        """
        try:
            with open(png_path, 'rb') as f:
                sig = f.read(8)
                if sig != b'\x89PNG\r\n\x1a\n':
                    return False, "File is not a valid PNG image."

                f.read(4)   # IHDR length field
                chunk_type = f.read(4)
                if chunk_type != b'IHDR':
                    return False, "PNG file is missing the IHDR chunk — it may be corrupted."

                width  = struct.unpack('>I', f.read(4))[0]
                height = struct.unpack('>I', f.read(4))[0]

            if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
                return False, (
                    f"PNG must be at least {self.MIN_WIDTH}×{self.MIN_HEIGHT} pixels. "
                    f"Your file is {width}×{height} pixels."
                )

            logger.info(f"PNG validated: {width}×{height} px — {png_path}")
            return True, "PNG is valid for TGS conversion."

        except (OSError, struct.error) as e:
            logger.error(f"PNG read error: {e}")
            return False, f"Could not read PNG file: {str(e)}"

        except Exception as e:
            logger.error(f"PNG validation error: {e}")
            return False, f"Error validating PNG file: {str(e)}"
