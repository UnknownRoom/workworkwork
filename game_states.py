import time
import logging
import random
from enum import Enum, auto
from typing import Dict, Any, Optional
from VisionResults import VisionResult

class GameState(Enum):
    """游戏外状态枚举"""
    GAME_START = auto()
    CHECK_IN = auto()
    LOG_IN = auto()
    CHANNEL_SELECT = auto()
    LOADING = auto()
    CREATE_ROLE = auto()
    """游戏内状态枚举"""
    MENU = auto()

def has_text(result: VisionResult, text: str) -> bool:
    return any(
        item.text.strip() == text
        for item in result.ocr_results
    )
def detect_game_state(result: VisionResult) -> GameState:
    texts = {
            item.text.strip()
            for item in result.ocr_results
            if item.confidence >= 0.6
        }
    
    if (
        "正在连接服务器" in texts and "取消" in texts
    ):
        return GameState.LOADING

    if (
        "删除角色" in texts
        and "创建" in texts
    ):
        return GameState.CREATE_ROLE

    if (
        "Kanal 1" in texts
        and "Kanal 2" in texts
        and "Kanal 3" in texts
        and "Kanal 4" in texts
        and "Kanal 5" in texts
    ):
        return GameState.CHANNEL_SELECT
    # 登录页面
    if (
        "用户名" in texts
        and "请输入你的账号" in texts
        and "密码" in texts
        and "请输入你的密码" in texts
        and "登录" in texts
    ):
        return GameState.LOG_IN

    if(
        "密码要求" in texts 
        and "消息注册" in texts
    ):
        return GameState.CHECK_IN
    if(
        "点击进入游戏" in texts
        and "点击加入游戏" in texts
    ):
        return GameState.GAME_START

    if(
        "切换频道" in texts
        and "商城" in texts
        and "个人商店编辑" in texts
        and "自动药水" in texts
        and "商城仓库" in texts
        and "市场搜索" in texts
        and "系统设置" in texts
        and "偏好设置" in texts
        and "更换角色" in texts

    ):
        return GameState.MENU

    return None