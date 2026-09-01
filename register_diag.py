# -*- coding: utf-8 -*-
"""
register_diag.py
============================================================
注册页诊断（实机校准用）：连接 VNC -> 切换语言 -> 点击注册 -> 抓注册页 -> 留档 + 全量 OCR。

用途：确认 CHECK_IN 页面的稳定中文签名（如「确认密码」）、字段顺序、勾选框数量，
作为 game_states.CHECK_IN 签名与 lifecycle 填表流程的校准依据。
"""
from __future__ import annotations

import logging
import sys
import time

import cv2
from vncdotool import api

import vnc_vision
from calibration import CalibrationStore
from fsm import RuntimeConfig
from game_states import Country
from input_controller import InputController
from lifecycle import OuterLifecycle
from targets import Target

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
    lifecycle.change_default_language()

    ctx = lifecycle._ctx()
    try:
        frame = capturer.grab()
    except Exception as exc:
        print(f"初始抓帧失败: {exc}")
        return 1
    ctx.frame = frame

    ok = lifecycle._click_target(
        ctx, Target(name="注册按钮", kind="template",
                    template_path="checkin.png", threshold=0.6)
    )
    print(f"点击注册按钮: {'成功' if ok else '失败'}")

    frame = None
    for i in range(12):
        time.sleep(1.0)
        try:
            frame = capturer.grab()
        except Exception as exc:
            print(f"抓帧失败: {exc}")
            continue
        texts = [t for t, _, _ in vision.read_all(frame)]
        print(f"[{i:2d}] 画面文本: {texts[:12]}")
        if any("确认密码" in t or "用户名" in t for t in texts):
            print(">>> 疑似进入注册页")
            break

    if frame is None:
        print("未能抓到注册页画面")
        return 1

    cv2.imwrite("debug_register_page.png", frame)
    print("已保存截图 debug_register_page.png")
    print("=" * 60)
    print("注册页全量 OCR（文本 | 置信度 | 中心坐标）:")
    for text, conf, poly, center in vision.read_all_detailed(frame):
        print(f"  '{text}' ({conf:.2f}) @ {center}")

    client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
