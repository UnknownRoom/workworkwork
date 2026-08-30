# -*- coding: utf-8 -*-
"""
main.py
============================================================
任务号脚本入口：连接 VNC -> 初始化组件 -> 提示用户定制目标 -> 运行生命周期。

CALIBRATE 校准清单（实机跑通前逐项确认，详见各模块内的 # CALIBRATE: 标注）：
    - VNC_HOST / VNC_PORT / VNC_PASSWORD / EXPECTED_SIZE 按实际环境填写。
    - OCR 后端（paddleocr/easyocr）与语言、是否 GPU。
    - 游戏内状态关键词、坐标、ROI、模板图、按键名。
"""
from __future__ import annotations

import logging
import sys

import vnc_vision
from calibration import CalibrationStore
from fsm import RuntimeConfig
from game_states import Country
from input_controller import InputController
from lifecycle import OuterLifecycle
from vncdotool import api

# ---- VNC 连接参数（CALIBRATE: 按实际环境填写）----
VNC_HOST = "127.0.0.1"
VNC_PORT = 5900
VNC_PASSWORD = "123456"

EXPECTED_SIZE = (1920, 1080)   # 预期分辨率

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def connect_vnc():
    """连接 VNC Server。"""
    print("=" * 50)
    print("正在连接 VNC...")
    print(f"地址: {VNC_HOST}:{VNC_PORT}")
    try:
        client = api.connect(f"{VNC_HOST}::{VNC_PORT}", password=VNC_PASSWORD)
        print("✅ VNC 连接成功")
        return client
    except Exception as e:
        print("❌ VNC 连接失败")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        return None


def check_screen(client) -> bool:
    """检查远程屏幕尺寸。"""
    try:
        width, height = client.screen.width, client.screen.height
        print(f"远程屏幕尺寸: {width} × {height}")
        if (width, height) == EXPECTED_SIZE:
            print("✅ 屏幕分辨率符合预期")
            return True
        print(f"⚠️ 屏幕分辨率与预期不一致（预期 {EXPECTED_SIZE[0]} × {EXPECTED_SIZE[1]}）")
        return False
    except Exception as e:
        print("❌ 无法获取远程屏幕信息")
        print(f"错误: {e}")
        return False


# ===========================================================================
# 运行时定制目标提示（纯文本回答）
# ===========================================================================
def prompt_country() -> Country:
    """提示选择国家，回答红/蓝/黄。"""
    while True:
        ans = input("请选择国家（回答颜色：红 / 蓝 / 黄）: ").strip()
        try:
            return Country.from_color(ans)
        except ValueError as e:
            print(f"  ⚠️ {e}，请重新输入")


def prompt_username() -> str:
    """提示输入目标用户名（交易/组队时要识别的账号 ID）。"""
    while True:
        ans = input("请输入目标用户名: ").strip()
        if ans:
            return ans
        print("  ⚠️ 用户名不能为空，请重新输入")


def prompt_channel() -> str:
    """提示输入目标频道（如 Kanal 1）。"""
    while True:
        ans = input("请输入目标频道（如 Kanal 1）: ").strip()
        if ans:
            return ans
        print("  ⚠️ 频道不能为空，请重新输入")


def build_config() -> RuntimeConfig:
    """组装运行时定制配置。"""
    print("\n" + "=" * 50)
    print("请补充定制目标")
    print("=" * 50)
    country = prompt_country()
    username = prompt_username()
    channel = prompt_channel()
    print(f"\n配置：国家={country.value}，目标用户名={username}，目标频道={channel}")
    return RuntimeConfig(country=country, username=username, channel=channel)


# ===========================================================================
# 主程序
# ===========================================================================
def main() -> int:
    client = connect_vnc()
    if client is None:
        print("\n程序终止：VNC 尚未连接成功")
        return 1

    vision = None  # 提前声明，避免 finally 中二次 NameError
    try:
        client.refreshScreen(incremental=False)
        screen_ok = check_screen(client)
        if not screen_ok:
            print("⚠️ 当前环境暂不符合预期，仍继续尝试运行...")

        capturer = vnc_vision.ScreenCapturer(client)
        controller = InputController(client)

        print("\n初始化 VisionEngine ...")
        # CALIBRATE: OCR 后端/语言/GPU 按实际环境调整
        vision = vnc_vision.VisionEngine(ocr_backend="paddleocr", languages=["ch"], gpu=False)
        print("✅ VisionEngine 初始化成功")

        config = build_config()

        store = CalibrationStore(path="calibration.json")

        lifecycle = OuterLifecycle(capturer, vision, controller, config, store)
        lifecycle.run()
        return 0

    except KeyboardInterrupt:
        print("\n用户中断")
        return 130
    except Exception as e:
        print("\n❌ 运行失败")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        return 1
    finally:
        try:
            client.disconnect()
            print("\nVNC 连接已关闭")
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
