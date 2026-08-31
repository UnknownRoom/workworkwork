# -*- coding: utf-8 -*-
"""
fsm.py
============================================================
通用状态机框架：Context / RuntimeConfig / Transition / StateMachine。

核心循环：
    grab() 抓帧 -> observe_state() 区域化识别当前状态
    -> 在迁移表里逐条尝试 action -> 成功(返回非 False)则推进，失败则计重试。

内建异常处理：
    - 每状态超时（同一观察状态持续超过 timeout 未推进）→ recover；
    - 重试耗尽（所有迁移 action 均失败达到 max_attempts）→ 触发 recover_action（如按 R 缩小）；
    - 未知状态（observe_state 返回 None）→ unknown_handler（截图留档 + esc 关弹窗 + 重试）；
    - 抓帧异常（VNC 断连）→ 记录并终止本轮（重连逻辑见 _grab 注释）。
============================================================
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from game_states import Country, GameState, observe_state
from calibration import report_problem

logger = logging.getLogger(__name__)


@dataclass
class RuntimeConfig:
    """运行时定制目标（main.py 提示用户输入）。"""
    country: Country             # 国家：红/蓝/黄
    username: str                # 目标用户名（登录校验/识别）
    channel: str                 # 目标频道（如 "Kanal 1"）
    timeout: float = 30.0        # 单个状态超时（秒）
    max_attempts: int = 3        # 单个状态最大重试次数


@dataclass
class Context:
    """状态机运行时共享上下文。"""
    capturer: Any                # ScreenCapturer
    vision: Any                  # VisionEngine
    controller: Any              # InputController
    config: RuntimeConfig
    running: bool = True
    attempts: Dict[str, int] = field(default_factory=dict)  # 每状态重试计数
    last_state: Optional[GameState] = None                  # 最近观察到的状态
    frame: Any = None                                       # 本循环最新帧（供 action 复用，避免重复抓帧）
    store: Any = None                                       # CalibrationStore（学习/复用 ROI 与模板四点框）


@dataclass
class Transition:
    """
    从「当前观察状态」出发的一条迁移。

    action 返回 bool：True 表示本步成功（游戏已推进/目标已点击），
    False/None 视为失败（目标未就绪）。action 抛异常也按失败处理。
    """
    target: GameState                                     # 期望进入的下一状态（日志用）
    action: Callable[[Context], Optional[bool]] = None    # 执行一步，返回是否成功
    condition: Callable[[Context, GameState], bool] = None  # 可选前置判断（None=跳过）
    recover_action: Callable[[Context], None] = None      # 重试耗尽时的补救（如按 R）


class StateMachine:
    """
    由「状态 -> 迁移列表」表驱动。

    :param table:      Dict[GameState, List[Transition]]，key 为当前观察状态。
    :param name:       状态机名（日志前缀）。
    :param timeout:    同一状态停留超过此时长触发 recover（秒）。
    :param max_attempts: 单个状态所有迁移均失败的最大次数，超过触发 recover_action。
    :param tick:       每次循环末尾的休眠秒数，避免空转。
    :param unknown_handler: 处理未知状态的回调；None 用默认实现。
    """

    def __init__(
        self,
        table: Dict[GameState, List[Transition]],
        name: str = "fsm",
        timeout: float = 30.0,
        max_attempts: int = 3,
        tick: float = 0.5,
        unknown_handler: Optional[Callable[[Context, Optional[GameState], Any], None]] = None,
    ):
        self.table = table
        self.name = name
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.tick = tick
        self.unknown_handler = unknown_handler or self._default_unknown

    # ------------------------------------------------------------------
    # 抓帧（带 VNC 断连保护）
    # ------------------------------------------------------------------
    def _grab(self, ctx: Context):
        try:
            return ctx.capturer.grab()
        except Exception as exc:
            # CALIBRATE: 若需要自动重连，可在此调用 capturer 的重连方法；
            # 当前 ScreenCapturer 未提供，故记录后终止本轮。
            logger.error("[%s] 抓帧失败（VNC 可能断连）: %s", self.name, exc)
            ctx.running = False
            return None

    # ------------------------------------------------------------------
    # 未知状态兜底
    # ------------------------------------------------------------------
    def _default_unknown(self, ctx: Context, state: Optional[GameState], frame=None) -> None:
        ctx.attempts["__unknown__"] = ctx.attempts.get("__unknown__", 0) + 1
        # 尝试 esc 关闭可能的弹窗，再重试
        try:
            ctx.controller.key_press("esc")
        except Exception:
            pass
        if ctx.attempts["__unknown__"] >= self.max_attempts:
            reason = (
                f"未知状态{' ' + state.name if state is not None else ''}"
                f"（连续 {self.max_attempts} 次无法识别）"
            )
            logger.warning("[%s] 未知状态重试耗尽，终止本轮", self.name)
            report_problem(frame, ctx.vision, reason, name=self.name)
            ctx.running = False

    # ------------------------------------------------------------------
    # 重试耗尽时的补救
    # ------------------------------------------------------------------
    def _recover(self, ctx: Context, state: GameState, transitions: List[Transition]) -> None:
        key = state.name
        ctx.attempts[key] = ctx.attempts.get(key, 0) + 1
        if ctx.attempts[key] >= self.max_attempts:
            recover_action = next(
                (t.recover_action for t in transitions if t.recover_action is not None),
                None,
            )
            if recover_action is not None:
                logger.info("[%s] 状态 %s 重试耗尽，触发补救动作", self.name, state.name)
                try:
                    recover_action(ctx)
                except Exception as exc:
                    logger.error("[%s] 补救动作失败: %s", self.name, exc)
            else:
                logger.warning("[%s] 状态 %s 重试耗尽，且无补救动作", self.name, state.name)
            ctx.attempts[key] = 0

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self, ctx: Context, stop_state: Optional[GameState] = None) -> bool:
        """运行状态机直到 ctx.running 被置 False 或抓帧失败。

        :param stop_state: 若提供，观察到该状态时立即正常结束（返回 True）。
        """
        logger.info("[%s] 状态机启动", self.name)
        state_entered_at: Optional[float] = None
        current_state: Optional[GameState] = None

        while ctx.running:
            frame = self._grab(ctx)
            if frame is None:
                break
            ctx.frame = frame

            # 候选状态：表里的 key + 所有迁移目标 + stop_state，
            # 否则 observe_state 永远观察不到终点状态，子状态机无法正常结束。
            candidates = set(self.table.keys())
            for transitions in self.table.values():
                for tr in transitions:
                    candidates.add(tr.target)
            if stop_state is not None:
                candidates.add(stop_state)

            observed = observe_state(
                frame,
                ctx.vision,
                candidates=candidates,
                store=ctx.store,
                config=ctx.config,
            )
            ctx.last_state = observed

            # 到达终点状态
            if stop_state is not None and observed == stop_state:
                logger.info("[%s] 到达终点状态 %s", self.name, stop_state.name)
                return True

            # 状态切换：重置计时与重试计数
            if observed != current_state:
                current_state = observed
                state_entered_at = time.monotonic()
                if observed is not None:
                    ctx.attempts[observed.name] = 0

            # 未知状态
            if observed is None:
                self.unknown_handler(ctx, None, frame)
                self._tick()
                continue

            transitions = self.table.get(observed, [])
            if not transitions:
                # 该状态没有定义出口迁移 → 视为无法推进，走兜底
                self.unknown_handler(ctx, observed, frame)
                self._tick()
                continue

            # 超时检查
            if state_entered_at is not None and (time.monotonic() - state_entered_at) > self.timeout:
                logger.warning("[%s] 状态 %s 超时，触发补救", self.name, observed.name)
                self._recover(ctx, observed, transitions)
                state_entered_at = time.monotonic()
                self._tick()
                continue

            # 逐条尝试迁移 action，第一个成功即推进
            advanced = False
            for tr in transitions:
                if tr.condition is not None and not tr.condition(ctx, observed):
                    continue
                ok = True
                if tr.action is not None:
                    try:
                        ok = tr.action(ctx) is not False
                    except Exception as exc:
                        logger.error("[%s] 状态 %s 动作异常: %s", self.name, observed.name, exc)
                        ok = False
                if ok:
                    advanced = True
                    ctx.attempts[observed.name] = 0
                    break

            if not advanced:
                self._recover(ctx, observed, transitions)

            self._tick()

        logger.info("[%s] 状态机结束", self.name)
        return ctx.running

    def _tick(self) -> None:
        if self.tick > 0:
            time.sleep(self.tick)
