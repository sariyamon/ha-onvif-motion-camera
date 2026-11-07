"""Fixtures for ONVIF Motion & Snapshot tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _fake_camera() -> MagicMock:
    cam = MagicMock()
    cam.update_xaddrs = AsyncMock()
    cam.close = AsyncMock()
    cam.get_snapshot = AsyncMock(return_value=JPEG)

    devicemgmt = MagicMock()
    devicemgmt.GetDeviceInformation = AsyncMock(
        return_value=SimpleNamespace(
            Manufacturer="TP-Link",
            Model="VIGI C340S",
            FirmwareVersion="3.2.1",
            SerialNumber="SN123",
        )
    )
    devicemgmt.GetNetworkInterfaces = AsyncMock(
        return_value=[
            SimpleNamespace(Enabled=True, Info=SimpleNamespace(HwAddress="74:FE:CE:89:7D:D5"))
        ]
    )
    devicemgmt.SystemReboot = AsyncMock()
    cam.create_devicemgmt_service = AsyncMock(return_value=devicemgmt)

    media = MagicMock()
    media.GetProfiles = AsyncMock(
        return_value=[
            SimpleNamespace(
                token="profile_1",
                Name="mainStream",
                VideoEncoderConfiguration=SimpleNamespace(
                    Encoding="H264", Resolution=SimpleNamespace(Width=2560, Height=1440)
                ),
            ),
            SimpleNamespace(
                token="profile_2",
                Name="minorStream",
                VideoEncoderConfiguration=SimpleNamespace(
                    Encoding="H264", Resolution=SimpleNamespace(Width=640, Height=360)
                ),
            ),
        ]
    )
    media.create_type = MagicMock(side_effect=lambda name: SimpleNamespace())
    media.GetStreamUri = AsyncMock(
        return_value=SimpleNamespace(Uri="rtsp://192.168.31.101:554/stream1")
    )
    cam.create_media_service = AsyncMock(return_value=media)

    from onvif.exceptions import ONVIFError

    # No live event feed in tests; events are injected with hub.process_event.
    cam.create_pullpoint_manager = AsyncMock(side_effect=ONVIFError("no events in tests"))
    return cam


@pytest.fixture
def fake_camera():
    cam = _fake_camera()
    with patch("custom_components.onvif_motion.hub.make_camera", return_value=cam):
        yield cam
