import time
import logging
import random
from enum import Enum, auto
from typing import Dict, Any, Optional
from VisionResults import VisionResult

class GameState(Enum):
    """游戏状态枚举"""
    GAME_START = auto()
    CHECK_IN = auto()
    LOG_IN = auto()
    CHANNEL_SELECT = auto()
    LOADING = auto()
    CREATE_ROLE = auto()
    MENU = auto()

def has_text(result: VisionResult, text: str) -> bool:
    return any(
        item.text.strip() == text
        for item in result.ocr_results
    )
def detect_game_state(result: VisionResult) -> GameState:

    if result.is_loading:
        
        return GameState.LOADING

    if result.has_create_role_page:

        return GameState.CREATE_ROLE

    if result.has_channel_select:

        return GameState.CHANNEL_SELECT

    texts = {
        item.text.strip()
        for item in result.ocr_results
        if item.confidence >= 0.6
    }
    # 登录页面
    if (
        "用户名" in texts
        and "请输入你的账号" in texts
        and "密码" in texts
        and "请输入你的密码" in texts
        and "登录" in texts
    ):
        return GameState.LOG_IN

    if result.has_register_page:

        return GameState.CHECK_IN

    if result.has_game_menu:

        return GameState.MENU

    return None