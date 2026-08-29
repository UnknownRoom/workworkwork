# -*- coding: utf-8 -*-
"""
vnc_vision.py
============================================================
基础图像采集与 OCR 识别核心工具库（VNC 远程环境）

设计目标：
    1. 全程内存流截图 —— 绝不把帧写入本地硬盘（禁用 cv2.imwrite）。
    2. 提供 ROI 裁剪 / 灰度 / 二值化 / 颜色阈值过滤等预处理能力。
    3. 封装 OCR 文本识别与定位（EasyOCR / PaddleOCR），返回全屏中心坐标。
    4. 封装 OpenCV 模板匹配，快速定位固定 UI 按钮。
    5. 封装鼠标 / 键盘模拟，带 50~150ms 随机网络延迟缓冲。

模块结构：
    ScreenCapturer    —— VNC 连接 + 内存流截图
    VisionEngine      —— 预处理 / ROI 裁剪 / OCR 识别 / 模板匹配
    InputController   —— 坐标映射 + 点击 / 按键模拟
    main()            —— 完整闭环测试示例

依赖：
    pip install vncdotool opencv-contrib-python numpy pillow
    OCR 二选一（或都装）：
        pip install paddleocr        # 中文效果好，推荐
        pip install easyocr          # 接口简单
============================================================
"""

from __future__ import annotations
# from input_controller import InputController
from vncdotool import api

import os
import sys
import random
import time
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from VisionResults import VisionResult,OCRResult

# ---------------------------------------------------------------------------
# 类型别名：坐标 / 边界框 / 识别结果
# ---------------------------------------------------------------------------
Point = Tuple[int, int]
BBox = Tuple[int, int, int, int]          # (x, y, w, h)，左上角坐标 + 宽高
TextHit = Tuple[bool, Optional[str], float, Optional[Point]]
                                          # (是否命中, 文本, 置信度, 全屏中心坐标)


# ===========================================================================
# 1. VNCClient / ScreenCapturer —— 内存流截图
# ===========================================================================
class ScreenCapturer:
    """
    VNC 客户端 + 内存流截图。

    核心要点：帧数据直接从 VNC framebuffer 读取并转换成 NumPy(BGR) 数组，
    全程不落盘，降低 I/O 与延迟。
    """

    def __init__(self,client):
        self. _client = client
        try:
            from vncdotool import api
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "缺少 vncdotool，请先执行: pip install vncdotool"
            ) from exc
       
        self._client.refreshScreen(incremental=False)

        screen = self._client.screen
        if screen is None:
            raise RuntimeError("VNC 连接已建立，但未收到画面帧")

        # 远端屏幕分辨率（用于坐标映射）。screen 是 PIL.Image，size=(宽, 高)
        self.width, self.height = screen.size
        self.screen_size: Tuple[int, int] = (self.width, self.height)

    # ------------------------------------------------------------------
    # 帧抓取：PIL(RGB) -> BGR NumPy 数组（全程内存，不落盘）
    # ------------------------------------------------------------------
    def grab(self) -> np.ndarray:
        """
        抓取一帧，直接返回内存中的 BGR NumPy 数组（不写盘）。

        vncdotool 1.x 已把 framebuffer 解码为 PIL.Image(screen, RGB 模式)，
        这里只需转成 OpenCV 惯用的 BGR 数组，无需再手工解析原始字节。
        """
        # 全量刷新：阻塞至本次 framebuffer 更新提交完成
        self._client.refreshScreen(incremental=False)

        screen = self._client.screen
        if screen is None:
            raise RuntimeError("未获取到画面帧")

        rgb = np.array(screen)  # (H, W, 3) uint8，RGB 顺序
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def close(self):
       pass  # VNCClient 不需要显式关闭，vncdotool 内部会自动管理 socket
# 别名，便于习惯不同命名的调用方
VNCClient = ScreenCapturer


# ===========================================================================
# 2. VisionEngine —— 预处理 / ROI / OCR / 模板匹配
# ===========================================================================
class VisionEngine:
    """图像处理与识别引擎（无状态、可复用）。"""

    # 支持的 OCR 后端
    BACKEND_EASYOCR = "easyocr"
    BACKEND_PADDLE = "paddleocr"

    def __init__(
        self,
        ocr_backend: str = "paddleocr",
        languages: Sequence[str] = ("ch"),
        gpu: bool = False,
        **ocr_kwargs: Any,
    ):
        """
        :param ocr_backend: 'easyocr' 或 'paddleocr'
        :param languages:   OCR 语言列表（EasyOCR: ['ch_sim','en']；PaddleOCR: ['ch','en']）
        :param gpu:         是否使用 GPU
        """
        self.ocr_backend = ocr_backend.lower()
        self.languages = list(languages)
        self._ocr = None
        self._init_ocr(gpu=gpu, **ocr_kwargs)

    # ------------------------------------------------------------------
    # OCR 引擎初始化
    # ------------------------------------------------------------------
    def _init_ocr(self, gpu: bool, **kwargs: Any) -> None:
        if self.ocr_backend == self.BACKEND_EASYOCR:
            try:
                import easyocr
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("缺少 easyocr，请先执行: pip install easyocr") from exc
            lang = self.languages if self.languages else ["ch_sim", "en"]
            self._ocr = easyocr.Reader(lang, gpu=gpu, **kwargs)

        elif self.ocr_backend == self.BACKEND_PADDLE:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("缺少 paddleocr，请先执行: pip install paddleocr") from exc

            # 3.x 默认参数：关闭与文字识别无关的版面/方向分类，加速
            lang = self.languages if self.languages else ["ch"]
            self._ocr = PaddleOCR(
                lang="".join(lang),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
                **kwargs,
            )

        else:
            raise ValueError(f"不支持的 OCR 后端: {self.ocr_backend!r}")

    # ------------------------------------------------------------------
    # ROI 裁剪
    # ------------------------------------------------------------------
    @staticmethod
    def crop_roi(frame: np.ndarray, bbox: BBox) -> np.ndarray:
        """
        按 bbox=(x, y, w, h) 裁剪 ROI，返回帧的视图（不复制，保持内存高效）。

        :return: 裁剪后的 ROI 图像（与 frame 共享内存，勿原位修改）
        """
        x, y, w, h = bbox
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            raise ValueError(f"非法 bbox: {bbox}")
        h_img, w_img = frame.shape[:2]
        x2, y2 = x + w, y + h
        if x2 > w_img or y2 > h_img:
            raise ValueError(f"bbox {bbox} 超出画面范围 {(w_img, h_img)}")
        return frame[y:y2, x:x2]

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    @staticmethod
    def to_gray(image: np.ndarray) -> np.ndarray:
        """灰度化。"""
        if image.ndim == 2:
            return image
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def binarize(
        image: np.ndarray,
        method: str = "otsu",
        threshold: int = 127,
        block_size: int = 15,
        c: int = 5,
        inverse: bool = False,
    ) -> np.ndarray:
        """
        二值化，输出单通道 0/255 图像。

        :param method: 'otsu'（大津，全局）、'fixed'（固定阈值）、'adaptive'（自适应，抗光照不均）
        :param inverse: True 表示白字黑底 -> 黑字白底反转
        """
        gray = VisionEngine.to_gray(image)
        flag = cv2.THRESH_BINARY_INV if inverse else cv2.THRESH_BINARY

        if method == "otsu":
            _, out = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)
        elif method == "fixed":
            _, out = cv2.threshold(gray, threshold, 255, flag)
        elif method == "adaptive":
            adp = cv2.ADAPTIVE_THRESH_GAUSSIAN_C if not inverse else cv2.ADAPTIVE_THRESH_MEAN_C
            out = cv2.adaptiveThreshold(gray, 255, adp, cv2.THRESH_BINARY, block_size, c)
            if inverse:
                out = cv2.bitwise_not(out)
        else:
            raise ValueError(f"不支持的二值化方法: {method!r}")
        return out

    @staticmethod
    def color_mask(
        image: np.ndarray,
        color_bgr: Tuple[int, int, int],
        tolerance: int = 25,
    ) -> np.ndarray:
        """
        颜色阈值过滤：提取指定颜色区域（如 NPC 名字 / 玩家 ID 的特定颜色文字）。

        内部转到 HSV 空间做范围过滤，对亮度变化更鲁棒。

        :param color_bgr: 目标颜色 (B, G, R)
        :param tolerance: HSV 各通道容差
        :return: 0/255 单通道掩码，目标颜色区域为 255
        """
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        target = np.uint8([[color_bgr]])
        target_hsv = cv2.cvtColor(target, cv2.COLOR_BGR2HSV)[0][0]

        lower = np.array(
            [
                max(0, int(target_hsv[0]) - tolerance),
                max(0, int(target_hsv[1]) - tolerance),
                max(0, int(target_hsv[2]) - tolerance),
            ]
        )
        upper = np.array(
            [
                min(179, int(target_hsv[0]) + tolerance),
                min(255, int(target_hsv[1]) + tolerance),
                min(255, int(target_hsv[2]) + tolerance),
            ]
        )
        return cv2.inRange(hsv, lower, upper)

    # ------------------------------------------------------------------
    # 统一 OCR 输出：内部归一化为 [(四点, 文本, 置信度), ...]
    # ------------------------------------------------------------------
    def _read_text(self, image: np.ndarray) -> List[Tuple[Any, str, float]]:
        """调用后端 OCR，返回归一化的 [(points, text, score), ...]。"""
        if self._ocr is None:
            raise RuntimeError("OCR 引擎未初始化")

        if self.ocr_backend == self.BACKEND_EASYOCR:
            return self._easyocr_read(image)

        return self._paddle_read(image)

    def _easyocr_read(self, image: np.ndarray) -> List[Tuple[Any, str, float]]:
        raw = self._ocr.readtext(image)
        # raw: [(bbox_4points, text, confidence), ...]
        return [(pts, txt, float(conf)) for (pts, txt, conf) in raw]

    def _paddle_read(self, image: np.ndarray) -> List[Tuple[Any, str, float]]:
        """兼容 PaddleOCR 2.x(ocr) 与 3.x(predict) 两套接口。"""
        if hasattr(self._ocr, "predict"):  # 3.x
            results = self._ocr.predict(image)
            out: List[Tuple[Any, str, float]] = []
            for res in results:
                texts = self._get(res, "rec_texts", [])
                scores = self._get(res, "rec_scores", [])
                polys = self._get(res, "rec_polys", None) or self._get(res, "dt_polys", [])
                for i, txt in enumerate(texts):
                    pts = polys[i] if polys and i < len(polys) else None
                    conf = float(scores[i]) if scores and i < len(scores) else 0.0
                    out.append((pts, str(txt), conf))
            return out

        # 2.x：ocr(img) -> [[ [ [x,y]x4 ], (text, score) ], ...]
        raw = self._ocr.predict(image, cls=False)
        if not raw:
            return []
        lines = raw[0] if isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], list) else raw
        return [(pts, str(txt), float(conf)) for (pts, (txt, conf)) in lines]

    @staticmethod
    def _get(obj: Any, key: str, default: Any) -> Any:
        """从 PaddleOCR 3.x 的 OCRResult 对象中安全取值。"""
        try:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)
        except Exception:
            return default

    @staticmethod
    def _poly_center(points: Any) -> Point:
        """四点 bbox -> 中心坐标。"""
        if points is None:
            return (0, 0)
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        return (int(round(sum(xs) / len(xs))), int(round(sum(ys) / len(ys))))

    # ------------------------------------------------------------------
    # OCR 文本识别与定位
    # ------------------------------------------------------------------
    def detect_text(
        self,
        image: np.ndarray,
        target_text: str,
        confidence: float = 0.6,
        offset: Tuple[int, int] = (0, 0),
        fuzzy: bool = False,
    ) -> TextHit:
        """
        在图像/ROI 中寻找目标文本（如 NPC 名字、账号 ID）。

        :param image:      待识别图像（通常是 crop_roi 的结果）
        :param target_text: 目标文本
        :param confidence: 置信度阈值
        :param offset:     ROI 在全屏中的左上角偏移 (ox, oy)，用于坐标换算
        :param fuzzy:       True 表示模糊匹配（target_text 是识别文本的子串，忽略大小写）
        :return: (是否命中, 匹配文本, 置信度, 全屏中心坐标)
        """
        target = target_text.lower()
        best: Optional[Tuple[float, str, Point]] = None

        for points, text, conf in self._read_text(image):
            if conf < confidence:
                continue
            if fuzzy:
                matched = target in text.lower()
            else:
                matched = text.strip().lower() == target
            if not matched:
                continue
            cx, cy = self._poly_center(points)
            if best is None or conf > best[0]:
                best = (conf, text, (cx + offset[0], cy + offset[1]))

        if best is None:
            return (False, None, 0.0, None)
        return (True, best[1], best[0], best[2])

    def read_all(
        self,
        image: np.ndarray,
        offset: Tuple[int, int] = (0, 0),
        min_confidence: float = 0.0,
    ) -> List[Tuple[str, float, Point]]:
        """返回图像中所有文本及其全屏坐标（可作调试/兜底）。"""
        out = []
        for points, text, conf in self._read_text(image):
            if conf < min_confidence:
                continue
            cx, cy = self._poly_center(points)
            out.append((text, conf, (cx + offset[0], cy + offset[1])))
        return out

    # ------------------------------------------------------------------
    # 模板匹配
    # ------------------------------------------------------------------
    @staticmethod
    def find_template(
        image: np.ndarray,
        template_path: str,
        threshold: float = 0.8,
        offset: Tuple[int, int] = (0, 0),
    ) -> Tuple[bool, Optional[Point]]:
        """
        模板匹配：定位固定 UI 按钮（如“确定”“交易”弹窗按钮）。

        :param image:         待搜索图像（全屏或 ROI）
        :param template_path: 模板图片路径（本函数仅用于读取模板，结果仍不落盘）
        :param threshold:     匹配阈值（0~1，越高越严格）
        :param offset:        ROI 在全屏中的偏移 (ox, oy)
        :return: (是否匹配, 全屏点击坐标)
        """
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"无法读取模板图片: {template_path}")

        res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < threshold:
            return (False, None)

        th, tw = template.shape[:2]
        # max_loc 是模板左上角，点击坐标取中心
        cx = max_loc[0] + tw // 2 + offset[0]
        cy = max_loc[1] + th // 2 + offset[1]
        return (True, (int(cx), int(cy)))
    
    def observe(self, frame: np.ndarray) -> VisionResult:
        """分析当前画面，并生成 VisionResult。"""
        ocr_results = self.read_all(frame)
        return VisionResult(
        ocr_results=[
            OCRResult(
                text=text,
                confidence=confidence,
                position=position,
            )
            for text, confidence, position in ocr_results
        ]
    )
    

# ===========================================================================
# 4. 完整闭环测试示例
# ===========================================================================
# def main() -> None:
#     """
#     演示：截取 VNC 画面 -> 指定 ROI 裁剪 -> OCR 识别 NPC 名字/ID
#           -> 算出全屏坐标 -> 输出识别结果及坐标。
#     """
#     # ---- 连接 VNC（按需修改为真实地址/密码）----
#     HOST, PORT, PASSWORD = "127.0.0.1", 5900, "123456"
#     capturer = ScreenCapturer(HOST, PORT, PASSWORD)

#     # ---- 初始化引擎 ----
#     vision = VisionEngine(ocr_backend="paddleocr", languages=["ch", "en"])
#     # controller = InputController(capturer)

#     try:
#         # 1. 内存流抓取一帧（不写盘）
#         frame = capturer.grab()
#         print(f"[capture] 画面尺寸: {frame.shape[1]}x{frame.shape[0]}")

#         # 2. 指定 ROI：假设 NPC 名字栏位于屏幕 (100, 200)，宽 300 高 40
#         npc_roi_bbox: BBox = (100, 200, 300, 40)
#         roi = vision.crop_roi(frame, npc_roi_bbox)

#         # 3. 预处理：灰度 + 二值化，提升 OCR 准确率
#         pre = vision.binarize(vision.to_gray(roi), method="otsu")

#         # 4. OCR 识别目标文本（offset 传入 ROI 左上角，用于换算全屏坐标）
#         target = "铁匠铺老板"
#         hit, text, conf, center = vision.detect_text(
#             pre, target, confidence=0.6, offset=npc_roi_bbox[:2], fuzzy=True
#         )

#         if hit:
#             print(f"[OCR] 命中: '{text}' (置信度 {conf:.2f}) @ 全屏坐标 {center}")
#             # 5. 输出识别结果及坐标，并可据此点击
#             # controller.click(*center)
#         else:
#             print(f"[OCR] 未命中目标 '{target}'")
#             # 兜底：打印该 ROI 内识别到的所有文本，便于调试
#             for t, c, p in vision.read_all(pre, offset=npc_roi_bbox[:2]):
#                 print(f"  - '{t}' ({c:.2f}) @ {p}")

#         # 6. 模板匹配示例：定位“确定”按钮
#         hit_tpl, pos = vision.find_template(frame, "assets/btn_ok.png", threshold=0.8)
#         if hit_tpl:
#             print(f"[template] 找到按钮 @ {pos}")
#             # controller.click(*pos)
#     finally:
#         capturer.close()


# if __name__ == "__main__":
#     main()
