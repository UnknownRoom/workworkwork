from __future__ import annotations

import random
import time
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from vnc_vision import ScreenCapturer


# ===========================================================================
# 3. InputController —— 坐标映射 + 点击 / 按键模拟
# ===========================================================================
class InputController:
    """
    输入事件网关：把屏幕坐标映射到 VNC 远端，并发送鼠标/键盘事件。

    每次事件之间加入 50~150ms 的随机网络延迟缓冲，避免指令堆积触发风控或丢包。
    """

    def __init__(
        self,
        capturer: ScreenCapturer,
        delay_range: Tuple[float, float] = (0.05, 0.15),
        scale: Tuple[float, float] = (1.0, 1.0),
    ):
        """
        :param capturer:    ScreenCapturer 实例（复用同一 VNC 连接）
        :param delay_range: 随机延迟区间 (min_sec, max_sec)，默认 50~150ms
        :param scale:       坐标缩放 (sx, sy)。当抓取的帧被缩放过（非 1:1）时使用。
        """
        self._capturer = capturer
        self._client = capturer._client
        self.delay_range = delay_range
        self.scale = scale

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _jitter(self) -> None:
        """随机网络延迟缓冲。"""
        lo, hi = self.delay_range
        time.sleep(random.uniform(lo, hi))

    def map_coords(self, x: int, y: int) -> Point:
        """把「抓取帧坐标系」映射到「VNC 远端坐标系」。"""
        sx, sy = self.scale
        return (int(round(x * sx)), int(round(y * sy)))

    # ------------------------------------------------------------------
    # 鼠标
    # ------------------------------------------------------------------
    def move(self, x: int, y: int) -> None:
        x, y = self.map_coords(x, y)
        self._client.mouseMove(x, y)
        self._jitter()

    def click(self, x: int, y: int, button: int = 1) -> None:
        """
        左键（默认 button=1）点击。
        VNC 按键号：1=左键 2=中键 3=右键。
        使用 mouseDown/mouseUp 组合，中间插入延迟模拟真实按压时长。
        """
        x, y = self.map_coords(x, y)
        self._client.mouseMove(x, y)
        self._jitter()
        self._client.mouseDown(button)
        self._jitter()
        self._client.mouseUp(button)
        self._jitter()

    def double_click(self, x: int, y: int, button: int = 1) -> None:
        self.click(x, y, button)
        self._jitter()
        self.click(x, y, button)

    def right_click(self, x: int, y: int) -> None:
        self.click(x, y, button=3)

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: int = 1) -> None:
        x1, y1 = self.map_coords(x1, y1)
        x2, y2 = self.map_coords(x2, y2)
        self._client.mouseMove(x1, y1)
        self._jitter()
        self._client.mouseDown(button)
        self._jitter()
        # 分步移动，模拟真人拖动轨迹
        steps = 8
        for i in range(1, steps + 1):
            mx = int(round(x1 + (x2 - x1) * i / steps))
            my = int(round(y1 + (y2 - y1) * i / steps))
            self._client.mouseMove(mx, my)
            self._jitter()
        self._client.mouseUp(button)
        self._jitter()

    # ------------------------------------------------------------------
    # 键盘
    # ------------------------------------------------------------------
    def key_press(self, key: str) -> None:
        """
        按下并释放一个键。key 为 vncdotool 的按键名，如 'enter'、'a'、'space'、'escape'。
        """
        self._client.keyPress(key)
        self._jitter()

    def key_combo(self, keys: Sequence[str]) -> None:
        """
        组合键（如 Ctrl+C）：传入 ['ctrl', 'c']。
        先依次按下，再逆序释放。
        """
        self._client.keyDown(keys[0])
        self._jitter()
        for k in keys[1:]:
            self._client.keyDown(k)
            self._jitter()
        for k in reversed(keys):
            self._client.keyUp(k)
            self._jitter()

    def type_text(self, text: str) -> None:
        """逐字符输入文本（仅覆盖可打印 ASCII，中文请用粘贴/剪贴板方案）。"""
        for ch in text:
            self._client.keyPress(ch)
            self._jitter()