# -*- coding: utf-8 -*-
"""
targets.py
============================================================
素材识别抽象：把「OCR 文本 / 模板图 / 固定坐标」统一成 Target，
并提供 find_target() 做区域化识别（只 OCR 目标 ROI，避免全屏 OCR）。

CALIBRATE 校准清单：
    - 每个 OCR 目标的 roi 实际区域 (x,y,w,h)，务必填写以提速。
    - 模板图的 template_path 需指向 assets/ 下真实截图（当前仓库无 assets/）。
    - fixed 目标的 point 为全屏绝对坐标。
============================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

Point = Tuple[int, int]
BBox = Tuple[int, int, int, int]  # (x, y, w, h)


@dataclass
class Target:
    """一个可识别/可点击的目标。"""
    name: str                          # 目标名（日志用）
    kind: str = "ocr"                  # "ocr" | "template" | "fixed"
    text: str = ""                     # kind=ocr 的目标文本
    template_path: str = ""            # kind=template 的模板图路径
    point: Point = (0, 0)              # kind=fixed 的全屏坐标
    roi: Optional[BBox] = None         # (x,y,w,h) 限定识别区域；None=全屏（慢）
    confidence: float = 0.6            # kind=ocr 置信度阈值
    fuzzy: bool = False                # kind=ocr 是否子串模糊匹配
    threshold: float = 0.8             # kind=template 匹配阈值


def _safe_crop(frame: np.ndarray, roi: BBox) -> np.ndarray:
    """裁剪 ROI，自动夹取到画面边界。"""
    x, y, w, h = roi
    h_img, w_img = frame.shape[:2]
    x = max(0, min(x, w_img - 1))
    y = max(0, min(y, h_img - 1))
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    return frame[y:y2, x:x2]


def find_target(frame: np.ndarray, target: Target, vision) -> Optional[Point]:
    """
    在 frame 中寻找 target，返回命中点的全屏中心坐标；未命中返回 None。

    roi 存在时先裁剪，只对 ROI 做识别，坐标用 offset=roi[:2] 换算回全屏。
    """
    if target.roi is not None:
        image = _safe_crop(frame, target.roi)
        offset = target.roi[:2]
    else:
        image = frame
        offset = (0, 0)
        if target.kind == "ocr":
            # CALIBRATE: 目标未指定 roi，会退化为全屏 OCR（慢）。请补 roi。
            logger.warning("Target %r 未指定 roi，将全屏 OCR（慢）", target.name)

    if target.kind == "ocr":
        hit, _, _, center = vision.detect_text(
            image,
            target.text,
            confidence=target.confidence,
            offset=offset,
            fuzzy=target.fuzzy,
        )
        return center if hit else None

    if target.kind == "template":
        hit, center = vision.find_template(
            image,
            target.template_path,
            threshold=target.threshold,
            offset=offset,
        )
        return center if hit else None

    if target.kind == "fixed":
        return (target.point[0] + offset[0], target.point[1] + offset[1])

    raise ValueError(f"不支持的 Target.kind: {target.kind!r}")
