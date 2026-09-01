# -*- coding: utf-8 -*-
"""
register_test.py
============================================================
仅跑「注册」环节的独立测试入口：连接 VNC -> 切换语言 -> 生成账号 -> 注册 -> 打印结果。

用于单环迭代注册表单，不必跑完整生命周期（main.py 会继续登录/建角色等）。
"""
from __future__ import annotations

import logging
import sys

from vncdotool import api

import vnc_vision
from calibration import CalibrationStore
from fsm import RuntimeConfig
from game_states import Country
from input_controller import InputController
from lifecycle import OuterLifecycle

VNC_HOST = "127.0.0.1"
VNC_PORT = 5900
VNC_PASSWORD = "123456"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    client = api.connect(f"{VNC_HOST}::{VNC_PORT}", password=VNC_PASSWORD)
    capturer = vnc_vision.ScreenCapturer(client)
    vision = vnc_vision.VisionEngine(ocr_backend="paddleocr", languages=["ch"], gpu=False)
    controller = InputController(client)
    store = CalibrationStore(path="calibration.json")
    config = RuntimeConfig(country=Country.RED, username="", channel="Kanal 1")

    lifecycle = OuterLifecycle(capturer, vision, controller, config, store)

    if not lifecycle.change_default_language():
        print("语言初始化失败，仍继续尝试注册...")

    lifecycle._generate_account()
    print(f"本次注册账号: {lifecycle.account['username']} / {lifecycle.account['password']}")

    ok = lifecycle.register()

    print("=" * 50)
    print(f"注册结果: {'成功' if ok else '失败'}")
    if ok:
        print(f"已进入登录页，账号: {lifecycle.account['username']}")

    client.disconnect()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
