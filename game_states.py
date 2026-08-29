# -*- coding: utf-8 -*-
"""
game_states.py
============================================================
游戏状态识别：枚举 + 声明式「签名表」驱动的区域化检测。

设计目标：
    1. 用统一的 GameState 枚举覆盖「游戏外」与「游戏内」状态。
    2. 用「签名表」STATE_SIGNATURES 声明每个状态需要出现的特征文本，
       替换原来一串手写 if，新增状态只需加一条声明。
    3. 每个签名可带 roi=(x,y,w,h)，observe_state() 会先对 ROI 去重、
       只 OCR 这些小块区域（而非全屏），再比对文本判定状态 —— 解决全屏 OCR 过慢。
    4. 提供离线可测的 detect_game_state(result) 与在线 observe_state(frame, vision)。

CALIBRATE 校准清单（实机跑通前必须逐项确认）：
    - 每个游戏内状态的真实 OCR 关键词（STATE_SIGNATURES 里是初值/占位）。
    - 每个签名的 roi 实际屏幕区域 (x,y,w,h)，填上即可大幅提速。
    - 职业识别名：创建角色选「武士」，但游戏内 OCR 识别名是「战士」。
============================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Iterable, List, Optional, Tuple

from VisionResults import OCRResult, VisionResult

# 边界框：(x, y, w, h)，左上角坐标 + 宽高
BBox = Tuple[int, int, int, int]


class GameState(Enum):
    """游戏状态枚举（游戏外 → 游戏内）。"""
    # ---- 游戏外 ----
    GAME_START = auto()       # 登录后点击进入游戏
    CHECK_IN = auto()         # 注册页
    LOG_IN = auto()           # 登录页
    CHANNEL_SELECT = auto()   # 频道选择
    LOADING = auto()          # 正在连接服务器
    CREATE_ROLE = auto()      # 创建角色页
    MENU = auto()             # 游戏内主菜单
    # ---- 游戏内 ----
    INVENTORY = auto()        # 背包/装备界面（按 i）
    AUTO_POTION = auto()      # 自动药水设置窗口
    HIDE_STALL = auto()       # 隐藏摆摊设置窗口
    MAP_OPEN = auto()         # 地图（按 m）
    FIGHTING = auto()         # 打怪升级中
    QUEST = auto()            # 任务面板
    NPC_DIALOG = auto()       # NPC 对话/接交任务
    TRADE = auto()            # 交易弹窗
    PARTY = auto()            # 组队
    RESPAWN = auto()          # 复活点


class Country(Enum):
    """国家枚举（红/蓝/黄），账号创建第一个角色时绑定。"""
    RED = "红"
    BLUE = "蓝"
    YELLOW = "黄"

    @classmethod
    def from_color(cls, s: str) -> "Country":
        """把用户输入（颜色中文/英文名）解析成 Country。"""
        s = s.strip()
        for c in cls:
            if s in (c.value, c.name, c.name.lower(), c.name.capitalize()):
                return c
        raise ValueError(f"无法识别的国家颜色: {s!r}（应为 红 / 蓝 / 黄）")


@dataclass(frozen=True)
class StateSignature:
    """状态的一个特征：屏幕上出现 text（可选限定在 roi 区域）即视为命中。"""
    text: str
    # CALIBRATE: 填该文本实际出现的屏幕区域 (x,y,w,h)；None 表示全屏（慢，尽量避免）。
    roi: Optional[BBox] = None
    confidence: float = 0.6


# ===========================================================================
# 状态签名表（声明式）
# ===========================================================================
# CALIBRATE:
#   - text 为实机 OCR 初值（游戏外状态沿用已有代码，游戏内状态为占位需确认）。
#   - roi 全部先置 None（回退全屏 OCR）；实机确认各文本位置后填具体区域以提速。
#   - 判定用「全部签名命中」的精确匹配（strip + 忽略大小写）。
STATE_SIGNATURES: Dict[GameState, List[StateSignature]] = {
    GameState.LOADING: [
        StateSignature("正在连接服务器"),
        StateSignature("取消"),
    ],
    GameState.CREATE_ROLE: [
        StateSignature("删除角色"),
        StateSignature("创建"),
    ],
    GameState.CHANNEL_SELECT: [
        StateSignature("Kanal 1"),
        StateSignature("Kanal 2"),
        StateSignature("Kanal 3"),
        StateSignature("Kanal 4"),
        StateSignature("Kanal 5"),
    ],
    GameState.LOG_IN: [
        StateSignature("用户名"),
        StateSignature("请输入你的账号"),
        StateSignature("密码"),
        StateSignature("请输入你的密码"),
        StateSignature("登录"),
    ],
    GameState.CHECK_IN: [
        StateSignature("密码要求"),
        StateSignature("消息注册"),
    ],
    GameState.GAME_START: [
        StateSignature("点击进入游戏"),
        StateSignature("点击加入游戏"),
    ],
    GameState.MENU: [
        StateSignature("切换频道"),
        StateSignature("商城"),
        StateSignature("个人商店编辑"),
        StateSignature("自动药水"),
        StateSignature("商城仓库"),
        StateSignature("市场搜索"),
        StateSignature("系统设置"),
        StateSignature("偏好设置"),
        StateSignature("更换角色"),
    ],
    # ---- 游戏内（占位初值，需实机校准） ----
    GameState.INVENTORY: [
        StateSignature("装备"),
        StateSignature("背包"),
    ],
    GameState.AUTO_POTION: [
        StateSignature("自动药水"),
        StateSignature("生命药水"),
    ],
    GameState.HIDE_STALL: [
        StateSignature("隐藏摆摊"),
    ],
    GameState.MAP_OPEN: [
        StateSignature("世界地图"),
    ],
    GameState.FIGHTING: [
        StateSignature("经验值"),
    ],
    GameState.QUEST: [
        StateSignature("任务"),
        StateSignature("可接受"),
    ],
    GameState.NPC_DIALOG: [
        StateSignature("接受任务"),
        StateSignature("完成任务"),
    ],
    GameState.TRADE: [
        StateSignature("交易"),
        StateSignature("确定"),
    ],
    GameState.PARTY: [
        StateSignature("组队"),
    ],
    GameState.RESPAWN: [
        StateSignature("复活点"),
    ],
}


# ===========================================================================
# 检测工具
# ===========================================================================
def has_text(result: VisionResult, text: str, confidence: float = 0.0) -> bool:
    """是否存在精确匹配的文本（不区分大小写，可带置信度下限）。"""
    target = text.strip().lower()
    return any(
        item.text.strip().lower() == target and item.confidence >= confidence
        for item in result.ocr_results
    )


def _in_roi(position: Tuple[int, int], roi: BBox) -> bool:
    """判断全屏中心坐标是否落在 roi 内。"""
    x, y = position
    rx, ry, rw, rh = roi
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def _signature_matched(sig: StateSignature, result: VisionResult) -> bool:
    target = sig.text.strip().lower()
    for item in result.ocr_results:
        if item.confidence < sig.confidence:
            continue
        if item.text.strip().lower() != target:
            continue
        if sig.roi is not None and not _in_roi(item.position, sig.roi):
            continue
        return True
    return False


def detect_game_state(
    result: VisionResult,
    signatures: Dict[GameState, List[StateSignature]] = STATE_SIGNATURES,
) -> Optional[GameState]:
    """
    根据已识别的 VisionResult 判定当前 GameState（离线可测）。

    按 STATE_SIGNATURES 的声明顺序返回第一个「全部签名命中」的状态；
    无匹配返回 None。
    """
    if result is None:
        return None
    for state, sigs in signatures.items():
        if sigs and all(_signature_matched(sig, result) for sig in sigs):
            return state
    return None


# ===========================================================================
# 在线区域化观察：只 OCR 签名表涉及的小块 ROI（避免全屏 OCR）
# ===========================================================================
def _safe_crop(frame, roi: BBox):
    """裁剪 ROI，自动夹取到画面边界（不抛异常）。"""
    x, y, w, h = roi
    h_img, w_img = frame.shape[:2]
    x = max(0, min(x, w_img - 1))
    y = max(0, min(y, h_img - 1))
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    return frame[y:y2, x:x2]


def _collect_signatures(
    candidates: Optional[Iterable[GameState]],
) -> List[StateSignature]:
    if candidates is None:
        out: List[StateSignature] = []
        for sigs in STATE_SIGNATURES.values():
            out.extend(sigs)
        return out
    out = []
    for state in candidates:
        out.extend(STATE_SIGNATURES.get(state, []))
    return out


def observe_state(
    frame,
    vision,
    candidates: Optional[Iterable[GameState]] = None,
) -> Optional[GameState]:
    """
    在线观察当前状态：按签名表规划识别区域，只 OCR 目标小块，再判定状态。

    :param frame:      当前画面（BGR NumPy 数组）
    :param vision:     VisionEngine 实例（需提供 read_all 方法）
    :param candidates: 候选状态集合（FSM 用它收窄 OCR 范围，None 表示全量）
    :return: GameState 或 None
    """
    sigs = _collect_signatures(candidates)

    rois = set()
    has_full = False
    for sig in sigs:
        if sig.roi is None:
            has_full = True
        else:
            rois.add(tuple(sig.roi))

    ocr_results: List[OCRResult] = []

    # 1) 先 OCR 所有非空 ROI（去重后每块只识别一次）
    for roi in rois:
        img = _safe_crop(frame, roi)
        for text, conf, pos in vision.read_all(img, offset=roi[:2]):
            ocr_results.append(OCRResult(text=text, confidence=conf, position=pos))

    # 2) 仅当存在无 ROI 的签名时才回退全屏 OCR（慢，尽量避免）
    if has_full:
        for text, conf, pos in vision.read_all(frame):
            ocr_results.append(OCRResult(text=text, confidence=conf, position=pos))

    return detect_game_state(VisionResult(ocr_results=ocr_results))
