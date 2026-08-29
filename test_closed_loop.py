# -*- coding: utf-8 -*-
"""
test_closed_loop.py
============================================================
闭环冒烟测试：抓帧 -> 区域化观察状态 -> 找目标 -> 点击。

需真实 VNC 环境（见 test.py 的连接方式）。用作验证
ScreenCapturer / VisionEngine / InputController / targets 是否串通。
"""
from __future__ import annotations

import time

from vncdotool import api

import vnc_vision
from game_states import observe_state
from input_controller import InputController
from targets import Target, find_target

VNC_HOST = "127.0.0.1"
VNC_PORT = 5900
VNC_PASSWORD = "123456"


def main() -> None:
    client = api.connect(f"{VNC_HOST}::{VNC_PORT}", password=VNC_PASSWORD)
    capturer = vnc_vision.ScreenCapturer(client)
    vision = vnc_vision.VisionEngine(ocr_backend="paddleocr", languages=["ch"], gpu=False)
    controller = InputController(client)

    frame = capturer.grab()
    state = observe_state(frame, vision)
    print(f"当前状态: {state}")

    # CALIBRATE: 目标文本/roi 需实机确认
    target = Target(name="进入游戏", kind="ocr", text="点击进入游戏", fuzzy=True)
    pos = find_target(frame, target, vision)
    if pos:
        print(f"发现目标 @ {pos}")
        controller.click(*pos)
    else:
        print("未发现目标")

    time.sleep(2)

    client.disconnect()


if __name__ == "__main__":
    main()
