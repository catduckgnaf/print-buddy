"""Synthetic resource regressions: never redistribute private model fixtures."""
import io
import zipfile
from unittest.mock import patch

import pytest

from print_buddy.core import intake_resources as limits


def test_large_mesh_refused_without_opening_member(tmp_path):
    source = tmp_path / 'large.3mf'
    # Compressible mesh-like XML is small on disk but exceeds the expanded budget.
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        with archive.open('3D/Objects/object_1.model', 'w') as member:
            for _ in range(33):
                member.write(b' ' * (1024 * 1024))
    with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('parsed mesh')):
        with pytest.raises(limits.IntakeLimitExceeded, match='XML.*32 MiB'):
            limits.check_source(source)


def test_download_limit_ignores_missing_or_false_content_length(tmp_path):
    target = tmp_path / 'model.3mf'
    with patch.object(limits, 'MAX_DOWNLOAD_BYTES', 8):
        with pytest.raises(limits.IntakeLimitExceeded, match='download'):
            limits.save_download(io.BytesIO(b'x' * 9), target)
    assert not target.exists()


def test_triangle_budget_before_dom_parse(tmp_path):
    source = tmp_path / 'mesh.3mf'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('3D/3dmodel.model', '<model><triangle/><triangle/></model>')
    with patch.object(limits, 'MAX_TRIANGLES', 1):
        with pytest.raises(limits.IntakeLimitExceeded, match='triangle'):
            limits.check_source(source)


def test_small_model_allowed(tmp_path):
    source = tmp_path / 'small.3mf'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('3D/3dmodel.model', '<model><triangle/></model>')
    limits.check_source(source)
