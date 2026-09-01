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

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Iterable, List, Optional, Tuple

from VisionResults import OCRResult, VisionResult
from calibration import normalize_text, polygon_to_bbox

logger = logging.getLogger(__name__)

# 边界框：(x, y, w, h)，左上角坐标 + 宽高
BBox = Tuple[int, int, int, int]


class GameState(Enum):
    """游戏状态枚举（游戏外 → 游戏内）。"""
    # ---- 游戏外 ----
    TITLE = auto()            # 标题页（登录/注册入口）
    GAME_START = auto()       # 登录后点击进入游戏
    CHECK_IN = auto()         # 注册页
    LOG_IN = auto()           # 登录页
    CHANNEL_SELECT = auto()   # 频道选择
    LOADING = auto()          # 正在连接服务器
    CREATE_ROLE = auto()      # 创建角色页
    COUNTRY_SELECT = auto()    # 选择国家页
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
        """把用户输入解析成 Country，支持数字(1/2/3)、首字母(R/B/Y)、颜色名(红/蓝/黄)。"""
        key = s.strip().upper()
        for i, c in enumerate(cls, start=1):
            if key in (str(i), c.name, c.name[0], c.value.upper(), c.value):
                return c
        raise ValueError(f"无法识别的国家: {s!r}（应为 1=红 2=蓝 3=黄，或 R/B/Y）")


@dataclass(frozen=True)
class StateSignature:
    """状态的一个特征：屏幕上出现 text（可选限定在 roi 区域）即视为命中。"""
    text: str
    # CALIBRATE: 填该文本实际出现的屏幕区域 (x,y,w,h)；None 表示全屏（慢，尽量避免）。
    roi: Optional[BBox] = None
    confidence: float = 0.6
    fuzzy: bool = False   # True 表示子串匹配（如 "Triarch" 匹配 "Triarch3"）


@dataclass(frozen=True)
class TemplateSignature:
    """状态的一个模板图特征：模板匹配（matchTemplate 分数）超过 threshold 即命中。

    template_path 可含 {country} 占位符，运行时按 config.country 解析为内置图片文件名。

    any_of=True 时，该状态下的多个模板为「任一命中即命中」（OR 关系）；
    默认 False 表示「全部命中才命中」（AND 关系）。
    """
    template_path: str
    threshold: float = 0.6
    roi: Optional[BBox] = None
    any_of: bool = False


# 国家 -> 国家关键字（用于 {country} 占位符解析，如 red/blue/yellow）。
COUNTRY_KEYWORD: Dict[Country, str] = {
    Country.RED: "red",
    Country.BLUE: "blue",
    Country.YELLOW: "yellow",
}


def resolve_template_path(path: str, config) -> str:
    """把模板路径里的 {country} 占位符替换为国家关键字（如 red）。"""
    if config is None or "{country}" not in path:
        return path
    keyword = COUNTRY_KEYWORD[config.country]
    return path.replace("{country}", keyword)


# ===========================================================================
# 状态签名表（声明式）
# ===========================================================================
# CALIBRATE:
#   - text 为实机 OCR 初值（游戏外状态沿用已有代码，游戏内状态为占位需确认）。
#   - roi 全部先置 None（回退全屏 OCR）；实机确认各文本位置后填具体区域以提速。
#   - 判定用「全部签名命中」的精确匹配（strip + 忽略大小写）。
STATE_SIGNATURES: Dict[GameState, List[StateSignature]] = {
    # TITLE 改用模板签名（checkin.png/login.png，见 TEMPLATE_SIGNATURES）
    GameState.LOADING: [
        StateSignature("正在连接服务器"),
        StateSignature("取消"),
    ],
    GameState.CREATE_ROLE: [
        StateSignature("删除角色"),
        StateSignature("创建"),
    ],
    GameState.COUNTRY_SELECT: [
        StateSignature("选择你的帝国"),
    ],
    GameState.CHANNEL_SELECT: [
        StateSignature("Kanal 1"),
        StateSignature("Kanal 2"),
        StateSignature("Kanal 3"),
        StateSignature("Kanal 4"),
        StateSignature("Kanal 5"),
    ],
    # CHECK_IN 改用 OCR 签名「确认密码」（注册页独有字段，登录页无）；LOG_IN 仍用模板签名 Channel.png。
    GameState.CHECK_IN: [
        # CALIBRATE: 注册页独有字段名，实机 OCR 确认后调整。
        StateSignature("消息"),
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
        StateSignature("物品栏"),
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
# 模板签名表（通用模板机制，战斗 UI 为首批数据）
# ===========================================================================
TEMPLATE_SIGNATURES: Dict[GameState, List[TemplateSignature]] = {
    GameState.TITLE: [
        TemplateSignature("checkin.png", threshold=0.6),
        TemplateSignature("login.png", threshold=0.6),
    ],
    GameState.LOG_IN: [
        TemplateSignature("Channel.png", threshold=0.6),
    ],
    GameState.FIGHTING: [
        TemplateSignature("fight_position_model/{country}_fight.png", threshold=0.6),
    ],
}

# 仅游戏内才识别的模板状态（战斗 UI 等）。游戏外（标题/注册/登录/创建角色）阶段
# observe_state 不得触碰这些模板，否则会因模板路径/内容不匹配而影响游戏外流程。
IN_GAME_TEMPLATE_STATES = {GameState.FIGHTING}


# ===========================================================================
# 检测工具
# ===========================================================================
def has_text(result: VisionResult, text: str, confidence: float = 0.0) -> bool:
    """是否存在精确匹配的文本（不区分大小写，可带置信度下限）。"""
    target = normalize_text(text)
    return any(
        normalize_text(item.text) == target and item.confidence >= confidence
        for item in result.ocr_results
    )


def _in_roi(position: Tuple[int, int], roi: BBox) -> bool:
    """判断全屏中心坐标是否落在 roi 内。"""
    x, y = position
    rx, ry, rw, rh = roi
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def _signature_matched(sig: StateSignature, result: VisionResult) -> bool:
    target = normalize_text(sig.text)
    for item in result.ocr_results:
        if item.confidence < sig.confidence:
            continue
        text = normalize_text(item.text)
        if sig.fuzzy:
            matched = target in text
        else:
            matched = text == target
        if not matched:
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


def _collect_ocr_signatures(
    candidates: Optional[Iterable[GameState]],
) -> List[Tuple[GameState, StateSignature]]:
    states = candidates if candidates is not None else list(STATE_SIGNATURES.keys())
    out: List[Tuple[GameState, StateSignature]] = []
    for state in states:
        for sig in STATE_SIGNATURES.get(state, []):
            out.append((state, sig))
    return out


def _collect_template_signatures(
    candidates: Optional[Iterable[GameState]],
    config,
) -> List[Tuple[GameState, TemplateSignature]]:
    """收集模板签名并解析国家占位符；无法解析（config 缺失）的签名跳过。"""
    if candidates is not None:
        states = list(candidates)
    else:
        # 未指定候选状态（如启动诊断）时，排除「仅游戏内」的模板状态，
        # 避免游戏外流程触碰战斗 UI 等模板导致误判或模板缺失报错。
        states = [s for s in TEMPLATE_SIGNATURES.keys() if s not in IN_GAME_TEMPLATE_STATES]
    out: List[Tuple[GameState, TemplateSignature]] = []
    for state in states:
        for sig in TEMPLATE_SIGNATURES.get(state, []):
            path = resolve_template_path(sig.template_path, config)
            if "{country}" in path:
                continue
            out.append((state, TemplateSignature(
                template_path=path,
                threshold=sig.threshold,
                roi=sig.roi,
                any_of=sig.any_of,
            )))
    return out


def _learn_ocr_boxes(store, sigs, ocr_results) -> None:
    """全屏 OCR 后，为缺少 ROI 的签名学习边界框并持久化到 store。"""
    if store is None:
        return
    changed = False
    for state, sig in sigs:
        if sig.roi is not None:
            continue
        key = store.ocr_key(state, sig.text)
        if key in store.ocr_boxes:
            continue
        target = normalize_text(sig.text)
        for item in ocr_results:
            if item.confidence < sig.confidence:
                continue
            text = normalize_text(item.text)
            if sig.fuzzy:
                matched = target in text
            else:
                matched = text == target
            if not matched:
                continue
            bbox = polygon_to_bbox(item.polygon)
            if bbox is None:
                cx, cy = item.position
                bbox = (max(0, cx - 4), max(0, cy - 4), 8, 8)
            store.ocr_boxes[key] = bbox
            changed = True
            logger.info("学习 OCR 签名 '%s' -> roi=%s", sig.text, bbox)
            break
    if changed:
        store.save()


def _observe_templates(frame, vision, tpl_sigs, store) -> Dict[GameState, bool]:
    """模板签名两阶段匹配（复用学习 bbox / 全屏学习），返回各状态是否命中。"""
    # 每个状态是 AND（默认）还是 OR（any_of=True）语义。
    any_of = {state: any(sig.any_of for sig in _sigs_for_state(tpl_sigs, state))
              for state in {state for state, _ in tpl_sigs}}
    hits: Dict[GameState, bool] = {}
    for state, sig in tpl_sigs:
        path = sig.template_path
        roi = sig.roi
        if roi is None and store is not None:
            roi = store.template_boxes.get(store.template_key(path))

        if roi is not None:
            img = _safe_crop(frame, roi)
            hit, corners, _ = vision.find_template_bbox(
                img, path, threshold=sig.threshold, offset=roi[:2]
            )
        else:
            hit, corners, _ = vision.find_template_bbox(
                frame, path, threshold=sig.threshold
            )
            if hit and store is not None and corners:
                bbox = polygon_to_bbox(corners, margin=8)
                if bbox is not None:
                    store.template_boxes[store.template_key(path)] = bbox
                    store.save()
                    logger.info("学习模板 '%s' -> 四点=%s", path, corners)

        if any_of.get(state, False):
            hits[state] = hits.get(state, False) or hit
        else:
            hits[state] = hits.get(state, True) and hit
    return hits


def _sigs_for_state(tpl_sigs, state) -> List[TemplateSignature]:
    return [sig for s, sig in tpl_sigs if s == state]


def _detect_state(
    ocr_result: VisionResult,
    template_hits: Dict[GameState, bool],
    candidates: Optional[Iterable[GameState]],
) -> Optional[GameState]:
    """结合 OCR 与模板签名的综合判定（保持声明顺序，模板状态需显式命中）。"""
    ordered = list(STATE_SIGNATURES.keys())
    for s in TEMPLATE_SIGNATURES:
        if s not in ordered:
            ordered.append(s)

    if candidates is not None:
        candidate_set = set(candidates)
        ordered = [s for s in ordered if s in candidate_set]

    for state in ordered:
        ocr_sigs = STATE_SIGNATURES.get(state, [])
        if ocr_sigs and not all(_signature_matched(sig, ocr_result) for sig in ocr_sigs):
            continue
        if TEMPLATE_SIGNATURES.get(state) and not template_hits.get(state, False):
            continue
        return state
    return None


def observe_state(
    frame,
    vision,
    candidates: Optional[Iterable[GameState]] = None,
    store=None,
    config=None,
) -> Optional[GameState]:
    """
    在线观察当前状态：按签名表规划识别区域，只 OCR 目标小块，再判定状态。

    :param frame:      当前画面（BGR NumPy 数组）
    :param vision:     VisionEngine 实例（需提供 read_all_detailed / find_template_bbox）
    :param candidates: 候选状态集合（FSM 用它收窄 OCR 范围，None 表示全量）
    :param store:      CalibrationStore（缺 ROI 时全屏学习并持久化，有则复用）
    :param config:     RuntimeConfig（解析模板路径的 {country} 占位符）
    :return: GameState 或 None
    """
    ocr_sigs = _collect_ocr_signatures(candidates)
    tpl_sigs = _collect_template_signatures(candidates, config)

    # ---- OCR：有学习 ROI 走快路径，缺 ROI 走全屏学习 ----
    ocr_results: List[OCRResult] = []
    rois = set()
    need_full = False
    for state, sig in ocr_sigs:
        roi = sig.roi
        if roi is None and store is not None:
            roi = store.ocr_boxes.get(store.ocr_key(state, sig.text))
        if roi is None:
            need_full = True
        else:
            rois.add(tuple(roi))

    if need_full:
        for text, conf, poly, center in vision.read_all_detailed(frame):
            ocr_results.append(OCRResult(text=text, confidence=conf, position=center, polygon=poly))
        _learn_ocr_boxes(store, ocr_sigs, ocr_results)
    else:
        for roi in rois:
            img = _safe_crop(frame, roi)
            for text, conf, poly, center in vision.read_all_detailed(img, offset=roi[:2]):
                ocr_results.append(OCRResult(text=text, confidence=conf, position=center, polygon=poly))

    # ---- 模板 ----
    template_hits = _observe_templates(frame, vision, tpl_sigs, store)

    return _detect_state(VisionResult(ocr_results=ocr_results), template_hits, candidates)
