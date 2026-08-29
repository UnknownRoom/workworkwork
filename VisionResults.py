from dataclasses import dataclass, field
from typing import List

from vnc_vision import TextHit


@dataclass
class OCRResult:
        text: str
        confidence: float
        position: tuple[int, int]
class VisionResult:
    
    # 原始 OCR 结果
    ocr_results: List[OCRResult]

    # 游戏外状态特征
    has_register_page: bool = False
    has_login_page: bool = False
    has_channel_select: bool = False
    is_loading: bool = False
    has_create_role_page: bool = False

    # 游戏内状态特征
    has_game_menu: bool = False
  