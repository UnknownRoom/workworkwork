# -*- coding: utf-8 -*-
"""
calibration.py
============================================================
自校准运行时：首次循环学习到的 ROI / 四点坐标的持久化与问题报告。

    CalibrationStore —— 保存学习结果到本地 JSON，供后续循环复用。
    polygon_to_bbox   —— OCR 四点文本框 -> (x, y, w, h) 边界框。
    report_problem    —— 全屏遍历后仍失败的统一报告（日志 + 截图）。
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Optional, Tuple

import cv2

logger = logging.getLogger(__name__)

Point = Tuple[int, int]
BBox = Tuple[int, int, int, int]  # (x, y, w, h)


def polygon_to_bbox(points, margin: int = 4) -> Optional[BBox]:
    """由 OCR 四点文本框算出外扩边界框 (x, y, w, h)；空输入返回 None。"""
    if not points:
        return None
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    x, y = min(xs), min(ys)
    w = max(xs) - x
    h = max(ys) - y
    x = max(0, x - margin)
    y = max(0, y - margin)
    return (x, y, w + 2 * margin, h + 2 * margin)


class CalibrationStore:
    """学习结果的本地 JSON 缓存（游戏外 OCR ROI + 游戏内模板四点框）。"""

    def __init__(self, path: str = "calibration.json"):
        self.path = path
        self.ocr_boxes: Dict[str, BBox] = {}
        self.template_boxes: Dict[str, BBox] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        self.ocr_boxes = {
            k: tuple(v) for k, v in data.get("ocr_boxes", {}).items()
        }
        self.template_boxes = {
            k: tuple(v) for k, v in data.get("template_boxes", {}).items()
        }

    def save(self) -> None:
        data = {
            "ocr_boxes": {k: list(v) for k, v in self.ocr_boxes.items()},
            "template_boxes": {k: list(v) for k, v in self.template_boxes.items()},
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def ocr_key(state, text: str) -> str:
        """OCR 签名的稳定缓存键（文本可能跨状态重复，故带状态名）。"""
        return f"{state.name}::{text}"

    @staticmethod
    def template_key(template_path: str) -> str:
        return template_path


def report_problem(frame, vision, reason: str, name: str = "fsm"):
    """
    全屏遍历后仍失败的统一报告：记错误日志 + 保存截图 + 打印全屏识别结果。

    返回 None（调用方据此置 ctx.running=False 终止本轮）。
    """
    logger.error("[%s] 报告问题: %s", name, reason)

    if frame is not None:
        try:
            cv2.imwrite(f"debug_{name}_problem.png", frame)
            logger.error("[%s] 已保存截图 debug_%s_problem.png", name, name)
        except Exception as exc:  # pragma: no cover
            logger.error("[%s] 保存截图失败: %s", name, exc)

    if vision is not None and frame is not None:
        try:
            details = vision.read_all_detailed(frame)
            logger.error("[%s] 全屏遍历识别结果（共 %d 条）:", name, len(details))
            for text, conf, poly, center in details:
                logger.error("    '%s' (%.2f) @ %s 四点=%s", text, conf, center, poly)
        except Exception as exc:  # pragma: no cover
            logger.error("[%s] 全屏遍历识别失败: %s", name, exc)

    return None
