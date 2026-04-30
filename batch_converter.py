"""
Batch SVG to TGS Converter
Handles multiple SVG files conversion — max files driven by the caller's plan.
"""

import os
import tempfile
import zipfile
import asyncio
import logging
from pathlib import Path

from converter import SVGToTGSConverter
from svg_validator import SVGValidator

logger = logging.getLogger(__name__)


class BatchConverter:
    def __init__(self):
        self.converter  = SVGToTGSConverter()
        self.validator  = SVGValidator()
        self.max_files  = 15   # hard cap; plan limit is enforced by the bot

    async def convert_batch(self, file_paths: list, original_names: list) -> dict:
        """
        Convert multiple SVG files concurrently.

        Returns a results dict:
            successful   : list of {success, file, tgs_path, tgs_size, output_name}
            failed       : list of {file, error}
            total_processed, success_count, error_count
        """
        if len(file_paths) > self.max_files:
            raise ValueError(f"Too many files — max {self.max_files}.")

        tasks   = [self._convert_one(fp, name, i)
                   for i, (fp, name) in enumerate(zip(file_paths, original_names))]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out = {'successful': [], 'failed': [],
               'total_processed': 0, 'success_count': 0, 'error_count': 0}

        for i, res in enumerate(results):
            out['total_processed'] += 1
            if isinstance(res, Exception):
                out['failed'].append({'file': original_names[i], 'error': str(res)})
                out['error_count'] += 1
            elif res['success']:
                out['successful'].append(res)
                out['success_count'] += 1
            else:
                out['failed'].append({'file': original_names[i], 'error': res['error']})
                out['error_count'] += 1

        return out

    async def _convert_one(self, file_path: str, original_name: str, index: int) -> dict:
        try:
            is_valid, err = self.validator.validate_svg_file(file_path)
            if not is_valid:
                return {'success': False, 'file': original_name, 'error': err}

            tgs_path = await self.converter.convert(file_path)
            return {
                'success':     True,
                'file':        original_name,
                'tgs_path':    tgs_path,
                'tgs_size':    os.path.getsize(tgs_path),
                'output_name': Path(original_name).stem + '.tgs',
            }
        except Exception as e:
            logger.error(f"Error converting {original_name}: {e}")
            return {'success': False, 'file': original_name, 'error': str(e)}

    def cleanup_temp_files(self, file_paths: list, tgs_paths: list | None = None):
        for p in (file_paths or []):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception as e:
                logger.warning(f"Could not delete {p}: {e}")
        for p in (tgs_paths or []):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception as e:
                logger.warning(f"Could not delete TGS {p}: {e}")

    def extract_files_from_zip(
        self, zip_path: str, max_files: int | None = None
    ) -> tuple[list, list, list]:
        """
        Extract SVG files from a ZIP archive.

        Returns (file_paths, original_names, errors).
        max_files defaults to self.max_files if not supplied.
        """
        limit       = max_files if max_files is not None else self.max_files
        file_paths  = []
        orig_names  = []
        errors      = []

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                svgs = [
                    n for n in zf.namelist()
                    if n.lower().endswith('.svg') and not n.startswith('__MACOSX/')
                ]
                if len(svgs) > limit:
                    errors.append(f"Too many SVG files — max {limit}. "
                                  f"First {limit} will be converted.")
                    svgs = svgs[:limit]

                for name in svgs:
                    try:
                        data = zf.read(name)
                        fd, tmp = tempfile.mkstemp(suffix='.svg')
                        with os.fdopen(fd, 'wb') as f:
                            f.write(data)
                        file_paths.append(tmp)
                        orig_names.append(os.path.basename(name))
                    except Exception as e:
                        errors.append(f"Could not extract {name}: {e}")

        except Exception as e:
            errors.append(f"Could not read ZIP: {e}")

        return file_paths, orig_names, errors
