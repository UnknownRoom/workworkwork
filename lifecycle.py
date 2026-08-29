# -*- coding: utf-8 -*-
"""
lifecycle.py
============================================================
任务号（task account）生命周期编排：

    OuterLifecycle —— 外层：注册 -> 登录 -> 创建角色 -> 进入游戏，循环多个角色。
    GameLifecycle  —— 内层：游戏内从主菜单到交易完整个流程。

采用 fsm.StateMachine 驱动，每个阶段一个子状态机。

CALIBRATE 校准清单（实机跑通前必须逐项确认，所有占位值都带 # CALIBRATE: 标注）：
    1. 各界面按钮/输入框坐标（POS_* 常量，默认 1920x1080）。
    2. 三国（红/蓝/黄）各自的打怪点/新兵教官/NPC 地图坐标（COUNTRY_WAYPOINTS）。
    3. 注册/登录表单字段坐标与账号规则。
    4. 交易/组队时识别目标用户名（仓库号/组队号 ID）出现在屏幕的区域。
    5. 按键名（i/m/r/escape/enter 等）与 vncdotool 键名一致性。
    6. 装备武器、自动药水、隐藏摆摊等界面的具体点击流程。

职业名注意：创建角色选「武士」，但游戏内 OCR 识别名是「战士」。
移动方式：m 键打开地图 -> 鼠标左键点击地图坐标即可自动寻路。
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional, Tuple

from fsm import Context, RuntimeConfig, StateMachine, Transition
from game_states import Country, GameState
from targets import Target, find_target

logger = logging.getLogger(__name__)


# ===========================================================================
# 占位坐标（CALIBRATE: 按实机 1920x1080 校准）
# ===========================================================================
POS_CREATE_ROLE = (0, 0)       # 创建角色按钮
POS_WARRIOR_CLASS = (0, 0)     # 选择战士职业
POS_CONFIRM_CREATE = (0, 0)    # 确认创建角色
POS_ENTER_GAME = (0, 0)        # 「点击进入游戏」按钮
POS_LOGIN = (0, 0)             # 登录按钮
POS_USERNAME_FIELD = (0, 0)    # 用户名输入框
POS_PASSWORD_FIELD = (0, 0)    # 密码输入框
POS_REGISTER = (0, 0)          # 注册提交按钮

# 三国地图坐标（CALIBRATE: 地图打开后点击的坐标，三国各一套，均为占位）
COUNTRY_WAYPOINTS: Dict[Country, Dict[str, Tuple[int, int]]] = {
    Country.RED: {
        "grind": (0, 0),        # 打怪点（升 2 级）
        "instructor": (0, 0),   # 新兵教官
        "zhanhun": (0, 0),      # 战魂
        "misc_merchant": (0, 0),# 杂货商人
        "armor_merchant": (0, 0),  # 防具商人
        "respawn": (0, 0),      # 复活点
    },
    Country.BLUE: {
        "grind": (0, 0),
        "instructor": (0, 0),
        "zhanhun": (0, 0),
        "misc_merchant": (0, 0),
        "armor_merchant": (0, 0),
        "respawn": (0, 0),
    },
    Country.YELLOW: {
        "grind": (0, 0),
        "instructor": (0, 0),
        "zhanhun": (0, 0),
        "misc_merchant": (0, 0),
        "armor_merchant": (0, 0),
        "respawn": (0, 0),
    },
}


# ===========================================================================
# 公共基类：Context 构建 + 点击/按键/占位检测
# ===========================================================================
class _LifecycleBase:
    def __init__(self, capturer, vision, controller, config: RuntimeConfig):
        self.capturer = capturer
        self.vision = vision
        self.controller = controller
        self.config = config

    def _ctx(self) -> Context:
        return Context(
            capturer=self.capturer,
            vision=self.vision,
            controller=self.controller,
            config=self.config,
        )

    # ------------------------------------------------------------------
    # 目标是否仍为占位（未校准）
    # ------------------------------------------------------------------
    @staticmethod
    def _is_placeholder(target: Target) -> bool:
        if target.kind == "fixed":
            return target.point == (0, 0)
        if target.kind == "ocr":
            return not target.text
        if target.kind == "template":
            return not target.template_path
        return True

    # ------------------------------------------------------------------
    # 找目标并点击；占位目标跳过（dry-run），未命中返回 False
    # ------------------------------------------------------------------
    def _click_target(self, ctx: Context, target: Target) -> bool:
        if self._is_placeholder(target):
            logger.warning("CALIBRATE: 目标 %r 尚未校准（占位），跳过点击", target.name)
            return True
        if ctx.frame is None:
            return False
        pos = find_target(ctx.frame, target, ctx.vision)
        if pos is None:
            return False
        ctx.controller.click(*pos)
        return True

    # ------------------------------------------------------------------
    # 找目标；未命中返回 None
    # ------------------------------------------------------------------
    def _find(self, ctx: Context, target: Target) -> Optional[Tuple[int, int]]:
        if self._is_placeholder(target):
            logger.warning("CALIBRATE: 目标 %r 尚未校准（占位）", target.name)
            return None
        if ctx.frame is None:
            return None
        return find_target(ctx.frame, target, ctx.vision)

    @staticmethod
    def _press(ctx: Context, key: str) -> bool:
        ctx.controller.key_press(key)
        return True

    @staticmethod
    def _recover_zoom_out(ctx: Context) -> None:
        """找不到 NPC 时按 R 缩小视角，避免玩家 ID 遮挡 NPC 名字。"""
        logger.info("补救：按 R 缩小视角")
        ctx.controller.key_press("r")


# ===========================================================================
# 外层生命周期：一个完整账号周期（注册->登录->创建->游戏内）
# ===========================================================================
class OuterLifecycle(_LifecycleBase):
    def __init__(self, capturer, vision, controller, config: RuntimeConfig):
        super().__init__(capturer, vision, controller, config)
        self.running = True
        self.create_count = 0
        self.language_initialized = False
        self.hide_stall_initialized = False
        self.account: Dict[str, str] = {"username": "", "password": ""}

    # ------------------------------------------------------------------
    # 全局一次性设置（游戏记忆，整个生命周期只执行一次）
    # ------------------------------------------------------------------
    def run(self):
        logger.info("OuterLifecycle 启动")
        self.change_default_language()

        while self.running:
            logger.info("开始第 %d 次角色创建", self.create_count + 1)
            if not self.register():
                continue
            if not self.login():
                continue
            if not self.create_character():
                continue
            self.enter_game()
            self.create_count += 1
            if self.create_count >= 5:
                # CALIBRATE: 任务号每个账号 5 个角色用完启用新任务号
                self.create_count = 0
                logger.info("本任务号 5 个角色已用完，应切换新任务号")

    # ------------------------------------------------------------------
    # 修改默认语言（只执行一次）
    # ------------------------------------------------------------------
    def change_default_language(self):
        if self.language_initialized:
            return
        # CALIBRATE: 实机确认「系统设置 -> 默认语言」的点击流程
        logger.warning("CALIBRATE: change_default_language 未实现，需实机校准")
        self.language_initialized = True

    # ------------------------------------------------------------------
    # 隐藏摆摊设置（游戏记忆，全局一次）
    # ------------------------------------------------------------------
    def setup_hide_stall(self, ctx: Context):
        if self.hide_stall_initialized:
            return
        # CALIBRATE: 实机确认隐藏摆摊设置入口与操作
        logger.warning("CALIBRATE: setup_hide_stall 未实现，需实机校准")
        self.hide_stall_initialized = True

    # ------------------------------------------------------------------
    # 注册：CHECK_IN -> LOG_IN
    # ------------------------------------------------------------------
    def register(self) -> bool:
        ctx = self._ctx()

        def do_register(c: Context) -> bool:
            # CALIBRATE: 生成账号规则需按游戏要求；此处用 ASCII 随机账号
            if not self.account["username"]:
                self.account["username"] = f"task{random.randint(100000, 999999)}"
                self.account["password"] = f"{random.randint(10000000, 99999999)}"
            logger.info("注册账号: %s", self.account["username"])
            # CALIBRATE: 填写注册表单并提交（字段坐标见 POS_*）
            self.controller.type_text(self.account["username"])
            return True

        fsm = StateMachine(
            {
                GameState.CHECK_IN: [
                    Transition(GameState.LOG_IN, action=do_register),
                ],
            },
            name="register",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx, stop_state=GameState.LOG_IN)
        return ctx.last_state == GameState.LOG_IN

    # ------------------------------------------------------------------
    # 登录：LOG_IN -> CHANNEL_SELECT -> GAME_START
    # ------------------------------------------------------------------
    def login(self) -> bool:
        ctx = self._ctx()

        def do_submit(c: Context) -> bool:
            # CALIBRATE: 点击用户名框 -> 输入 -> 点密码框 -> 输入 -> 点登录
            self.controller.type_text(self.account["username"])
            self.controller.type_text(self.account["password"])
            return self._click_target(c, Target(name="登录按钮", kind="fixed", point=POS_LOGIN))

        def do_select_channel(c: Context) -> bool:
            # CALIBRATE: 频道名在屏幕上出现的区域需校准 roi
            return self._click_target(
                c,
                Target(name="目标频道", kind="ocr", text=self.config.channel, fuzzy=True),
            )

        fsm = StateMachine(
            {
                GameState.LOG_IN: [
                    Transition(GameState.CHANNEL_SELECT, action=do_submit),
                ],
                GameState.CHANNEL_SELECT: [
                    Transition(GameState.GAME_START, action=do_select_channel),
                ],
            },
            name="login",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx, stop_state=GameState.GAME_START)
        return ctx.last_state == GameState.GAME_START

    # ------------------------------------------------------------------
    # 创建角色：GAME_START -> CREATE_ROLE -> LOADING -> MENU
    # ------------------------------------------------------------------
    def create_character(self) -> bool:
        ctx = self._ctx()

        def do_enter(c: Context) -> bool:
            return self._click_target(c, Target(name="点击进入游戏", kind="fixed", point=POS_ENTER_GAME))

        def do_create(c: Context) -> bool:
            # CALIBRATE: 创建战士（OCR 识别名「战士」）+ 绑定国家
            self.controller.click(*POS_WARRIOR_CLASS)
            self._bind_country(c)
            self.controller.click(*POS_CONFIRM_CREATE)
            return True

        fsm = StateMachine(
            {
                GameState.GAME_START: [
                    Transition(GameState.CREATE_ROLE, action=do_enter),
                ],
                GameState.CREATE_ROLE: [
                    Transition(GameState.LOADING, action=do_create),
                ],
            },
            name="create_character",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx, stop_state=GameState.MENU)
        return ctx.last_state == GameState.MENU

    def _bind_country(self, ctx: Context) -> None:
        # CALIBRATE: 第一个角色绑定国家（红/蓝/黄）的界面操作，需实机确认
        logger.warning("CALIBRATE: 绑定国家 %s 未实现，需实机校准", self.config.country.value)

    # ------------------------------------------------------------------
    # 进入游戏内部循环
    # ------------------------------------------------------------------
    def enter_game(self):
        logger.info("进入游戏")
        game_loop = GameLifecycle(
            self.capturer, self.vision, self.controller, self.config
        )
        game_loop.run()


# ===========================================================================
# 内层生命周期：游戏内从主菜单到交易完整流程
# ===========================================================================
class GameLifecycle(_LifecycleBase):
    def __init__(self, capturer, vision, controller, config: RuntimeConfig):
        super().__init__(capturer, vision, controller, config)
        # 每角色一次（新角色需要；游戏会记忆的设置不在这里）
        self.equip_weapon_done = False
        self.auto_potion_done = False

    def run(self):
        ctx = self._ctx()
        fsm = StateMachine(
            self._table(),
            name="game",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx)

    # ------------------------------------------------------------------
    # 迁移表：MENU -> ... -> TRADE（线性流程，NPC 相关步骤带按 R 补救）
    # ------------------------------------------------------------------
    def _table(self) -> Dict[GameState, List[Transition]]:
        return {
            GameState.MENU: [
                Transition(GameState.INVENTORY, action=self._equip_weapon),
            ],
            GameState.INVENTORY: [
                Transition(GameState.AUTO_POTION, action=self._setup_auto_potion),
            ],
            GameState.AUTO_POTION: [
                Transition(GameState.HIDE_STALL, action=self._setup_hide_stall),
            ],
            GameState.HIDE_STALL: [
                Transition(GameState.MAP_OPEN, action=self._open_map_to_grind),
            ],
            GameState.MAP_OPEN: [
                Transition(GameState.FIGHTING, action=self._click_grind_waypoint),
            ],
            GameState.FIGHTING: [
                Transition(GameState.QUEST, action=self._open_quest),
            ],
            GameState.QUEST: [
                Transition(GameState.NPC_DIALOG, action=self._go_instructor,
                           recover_action=self._recover_zoom_out),
            ],
            GameState.NPC_DIALOG: [
                Transition(GameState.FIGHTING, action=self._accept_quest,
                           recover_action=self._recover_zoom_out),
            ],
            # CALIBRATE: 后续战魂/杂货商人/组队/防具商人/出售/交易 流程复杂，
            # 此处给出结构占位，需实机逐步校准各步骤坐标与顺序。
        }

    # ------------------------------------------------------------------
    # 各步骤动作（占位，需实机校准）
    # ------------------------------------------------------------------
    def _equip_weapon(self, ctx: Context) -> bool:
        if self.equip_weapon_done:
            return True
        # CALIBRATE: 按 i 打开背包装备武器
        self._press(ctx, "i")
        self.equip_weapon_done = True
        return True

    def _setup_auto_potion(self, ctx: Context) -> bool:
        # 每角色一次
        if self.auto_potion_done:
            return True
        # CALIBRATE: 打开自动药水设置并开启
        logger.warning("CALIBRATE: _setup_auto_potion 未实现，需实机校准")
        self.auto_potion_done = True
        return True

    def _setup_hide_stall(self, ctx: Context) -> bool:
        # CALIBRATE: 隐藏摆摊设置（游戏记忆，其实全局一次，但此处每角色跳过）
        logger.warning("CALIBRATE: _setup_hide_stall 未实现，需实机校准")
        return True

    def _waypoint(self, key: str) -> Tuple[int, int]:
        return COUNTRY_WAYPOINTS[self.config.country][key]

    def _open_map_to_grind(self, ctx: Context) -> bool:
        # m 键打开地图
        return self._press(ctx, "m")

    def _click_grind_waypoint(self, ctx: Context) -> bool:
        # 左键点击地图打怪点坐标 -> 自动寻路
        x, y = self._waypoint("grind")
        if (x, y) == (0, 0):
            logger.warning("CALIBRATE: 打怪点坐标未校准，跳过")
            return True
        ctx.controller.click(x, y)
        return True

    def _open_quest(self, ctx: Context) -> bool:
        # CALIBRATE: 打开任务面板的操作
        logger.warning("CALIBRATE: _open_quest 未实现，需实机校准")
        return True

    def _go_instructor(self, ctx: Context) -> bool:
        # m 打开地图 -> 点新兵教官坐标
        self._press(ctx, "m")
        x, y = self._waypoint("instructor")
        if (x, y) == (0, 0):
            logger.warning("CALIBRATE: 新兵教官坐标未校准，跳过")
            return True
        ctx.controller.click(x, y)
        return True

    def _accept_quest(self, ctx: Context) -> bool:
        # CALIBRATE: 接受任务的点击流程
        logger.warning("CALIBRATE: _accept_quest 未实现，需实机校准")
        return True
