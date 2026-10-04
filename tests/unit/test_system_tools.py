"""Unit tests for SystemTool, BrightnessController, and VolumeController."""

import pytest
from lyra.computer.brightness import BrightnessController
from lyra.computer.volume import VolumeController
from lyra.models.tools import ToolRequest
from lyra.tools.system_tool import SystemTool


def test_brightness_controller_mock_lifecycle():
    ctrl = BrightnessController(use_mock=True)
    assert ctrl.get_brightness() == 0.5

    ctrl.set_brightness(0.8)
    assert ctrl.get_brightness() == 0.8

    ctrl.increase_brightness(0.1)
    assert ctrl.get_brightness() == 0.9

    ctrl.decrease_brightness(0.2)
    assert ctrl.get_brightness() == 0.7


def test_volume_controller_mock_lifecycle():
    ctrl = VolumeController(use_mock=True)
    state = ctrl.get_volume()
    assert state["volume"] == 50
    assert not state["muted"]

    ctrl.set_volume(80)
    assert ctrl.get_volume()["volume"] == 80

    ctrl.increase_volume(10)
    assert ctrl.get_volume()["volume"] == 90

    ctrl.decrease_volume(20)
    assert ctrl.get_volume()["volume"] == 70

    ctrl.mute()
    assert ctrl.get_volume()["muted"]

    ctrl.unmute()
    assert not ctrl.get_volume()["muted"]


def test_system_tool_brightness_execution():
    import asyncio

    async def _test():
        b_ctrl = BrightnessController(use_mock=True)
        v_ctrl = VolumeController(use_mock=True)
        tool = SystemTool(brightness_controller=b_ctrl, volume_controller=v_ctrl)

        # Set brightness
        req_set = ToolRequest(tool_name="system", arguments={"action": "set_brightness", "level": 60})
        res_set = await tool.execute(req_set)
        assert res_set.success
        assert res_set.output["brightness"] == 0.6
        assert "60%" in tool.format_result(res_set)

        # Increase brightness
        req_inc = ToolRequest(tool_name="system", arguments={"action": "increase_brightness", "delta": 10})
        res_inc = await tool.execute(req_inc)
        assert res_inc.success
        assert res_inc.output["brightness"] == 0.7

    asyncio.run(_test())


def test_system_tool_volume_execution():
    import asyncio

    async def _test():
        b_ctrl = BrightnessController(use_mock=True)
        v_ctrl = VolumeController(use_mock=True)
        tool = SystemTool(brightness_controller=b_ctrl, volume_controller=v_ctrl)

        # Set volume
        req_vol = ToolRequest(tool_name="system", arguments={"action": "set_volume", "level": 40})
        res_vol = await tool.execute(req_vol)
        assert res_vol.success
        assert res_vol.output["volume"] == 40
        assert "40%" in tool.format_result(res_vol)

        # Mute
        req_mute = ToolRequest(tool_name="system", arguments={"action": "mute"})
        res_mute = await tool.execute(req_mute)
        assert res_mute.success
        assert res_mute.output["muted"]
        assert "Muted" in tool.format_result(res_mute)

    asyncio.run(_test())
