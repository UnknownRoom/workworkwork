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

import json
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

# 用户定制持久化文件（保存国家等选项，避免每次启动重复选择）
USER_CONFIG_PATH = "user_config.json"

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
        # timeout: 每次同步调用（如 refreshScreen）的最长等待秒数，避免服务器不响应时无限阻塞
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
def _load_user_config() -> dict:
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_user_config(data: dict) -> None:
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("", "y", "yes")


def prompt_country() -> Country:
    """提示选择国家，支持数字(1/2/3)或首字母(R/B/Y)，并询问是否一直保持该国家。"""
    cfg = _load_user_config()
    saved = cfg.get("country")
    if saved:
        try:
            saved_country = Country.from_color(saved)
        except ValueError:
            saved_country = None
        if saved_country is not None:
            ans = input(f"已保存国家：{saved_country.value}，是否沿用？(y/n，默认 y): ")
            if _yes(ans):
                print(f"  沿用国家：{saved_country.value}")
                return saved_country

    while True:
        ans = input("请选择国家（1=红 2=蓝 3=黄，或输入 R/B/Y）: ").strip()
        try:
            country = Country.from_color(ans)
        except ValueError as e:
            print(f"  ⚠️ {e}，请重新输入")
            continue
        keep = input("是否一直保持当前国家选项？(y/n，默认 y): ")
        if _yes(keep):
            cfg["country"] = country.value
            _save_user_config(cfg)
            print(f"  已保存国家：{country.value}（下次启动自动沿用）")
        return country


def prompt_username() -> str:
    """提示输入目标用户名（交易/组队时要识别的账号 ID）。"""
    while True:
        ans = input("请输入目标用户名: ").strip()
        if ans:
            return ans
        print("  ⚠️ 用户名不能为空，请重新输入")


# 频道号/字母 -> 实际频道名（Kanal 1~5）
_CHANNEL_MAP = {
    "1": "Kanal 1", "2": "Kanal 2", "3": "Kanal 3", "4": "Kanal 4", "5": "Kanal 5",
    "A": "Kanal 1", "B": "Kanal 2", "C": "Kanal 3", "D": "Kanal 4", "E": "Kanal 5",
}


def prompt_channel() -> str:
    """提示输入目标频道，支持数字(1-5)或大写字母(A-E)。"""
    while True:
        ans = input("请输入目标频道（1-5，或大写字母 A-E）: ").strip().upper()
        if ans in _CHANNEL_MAP:
            return _CHANNEL_MAP[ans]
        print("  ⚠️ 请输入 1-5 或 A-E")


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

        # 先让用户回答定制目标，再加载慢的 OCR 模型，避免交互前长时间无输出
        config = build_config()

        print("\n创建 ScreenCapturer ...", flush=True)
        capturer = vnc_vision.ScreenCapturer(client)
        print("✅ ScreenCapturer 就绪", flush=True)

        controller = InputController(client)
        print("✅ InputController 就绪", flush=True)

        print("\n初始化 VisionEngine ...", flush=True)
        print("正在加载 OCR 模型，首次运行会下载模型，可能需要数分钟，请耐心等待...", flush=True)
        # CALIBRATE: OCR 后端/语言/GPU 按实际环境调整
        try:
            vision = vnc_vision.VisionEngine(ocr_backend="paddleocr", languages=["ch"], gpu=False)
        except Exception as e:
            print("\n❌ OCR 引擎初始化失败", flush=True)
            print(f"错误: {e}", flush=True)
            print(
                "提示: paddleocr 后端需要 paddlepaddle 框架（pip install paddlepaddle）；\n"
                "      或改用 easyocr 后端（需先下载模型）。",
                flush=True,
            )
            raise
        print("✅ VisionEngine 初始化成功", flush=True)

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
