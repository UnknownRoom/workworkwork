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

def detect_game_state(result: VisionResult) -> GameState:

    if result.is_loading:
        
        return GameState.LOADING

    if result.has_create_role_page:

        return GameState.CREATE_ROLE

    if result.has_channel_select:

        return GameState.CHANNEL_SELECT

    if result.has_login_page:

        return GameState.LOG_IN

    if result.has_register_page:

        return GameState.CHECK_IN

    if result.has_game_menu:

        return GameState.MENU

    return GameState.GAME_START