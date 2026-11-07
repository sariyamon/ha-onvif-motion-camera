"""The ready-made dashboard cards ship with the integration and are loaded."""
import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.onvif_motion import CARDS_FILE, CARDS_URL

ROOT = Path(__file__).parent.parent / "custom_components" / "onvif_motion"


def test_cards_file_matches_manifest_version() -> None:
    version = json.loads((ROOT / "manifest.json").read_text())["version"]
    text = CARDS_FILE.read_text()
    assert f'const VERSION = "{version}"' in text
    for tag in (
        "onvif-motion-last-motion-card",
        "onvif-motion-live-card",
        "onvif-motion-detections-card",
        "onvif-motion-alerts-card",
        "onvif-motion-controls-card",
        "onvif-motion-dashboard-card",
    ):
        assert f'"{tag}"' in text


async def test_cards_registered(hass: HomeAssistant) -> None:
    """With the frontend loaded, the cards file is served and added to every page."""
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")  # the real frontend needs its web files
    added: list[str] = []
    with patch(
        "custom_components.onvif_motion.add_extra_js_url",
        side_effect=lambda _hass, url: added.append(url),
    ), patch.object(hass.http, "async_register_static_paths") as static:
        assert await async_setup_component(hass, "onvif_motion", {})
        await hass.async_block_till_done()
    version = json.loads((ROOT / "manifest.json").read_text())["version"]
    assert added == [f"{CARDS_URL}?v={version}"]
    config = static.call_args.args[0][0]
    assert config.url_path == CARDS_URL and Path(config.path) == CARDS_FILE
