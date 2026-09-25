import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.dxf_import.importer import _classify_layer


def test_classify_tag_layer():
    assert _classify_layer("RFID_TAG") == "tag"
    assert _classify_layer("rfid-tags-up") == "tag"
    assert _classify_layer("R-TAG-MAIN") == "tag"


def test_classify_element_layer():
    assert _classify_layer("SIGNAL-MAIN") == "element"
    assert _classify_layer("LC_GATE") == "element"
    assert _classify_layer("TURNOUT-01") == "element"
    assert _classify_layer("FOULING_MARK") == "element"
    assert _classify_layer("BSLB") == "element"


def test_classify_unclassified():
    assert _classify_layer("DIMENSIONS") == "unclassified"
    assert _classify_layer("0") == "unclassified"
    assert _classify_layer("TITLE_BLOCK") == "unclassified"


def test_import_dxf_without_ezdxf_gives_clear_warning():
    """If ezdxf isn't installed, import_dxf must fail loudly with an actionable
    message, not silently return an empty/misleading result."""
    import app.dxf_import.importer as importer_mod
    original = importer_mod.ezdxf
    importer_mod.ezdxf = None
    try:
        result = importer_mod.import_dxf("/nonexistent/path.dxf")
        assert result.candidates == []
        assert any("pip install ezdxf" in w for w in result.warnings)
    finally:
        importer_mod.ezdxf = original
