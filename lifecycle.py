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
    5. 按键名（i/m/r/esc/enter 等）与 vncdotool 键名一致性。
    6. 装备武器、自动药水、隐藏摆摊等界面的具体点击流程。

职业名注意：创建角色选「武士」，但游戏内 OCR 识别名是「战士」。
移动方式：m 键打开地图 -> 鼠标左键点击地图坐标即可自动寻路。
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from calibration import normalize_text, polygon_to_bbox, report_problem
from fsm import Context, RuntimeConfig, StateMachine, Transition
from game_states import Country, GameState, TEMPLATE_SIGNATURES, observe_state, resolve_template_path
from targets import Target, find_target

logger = logging.getLogger(__name__)

# 外层生命周期连续失败上限（超过则终止，避免无限重试死循环）
MAX_CONSECUTIVE_FAILURES = 3


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

# 国家选择页国旗模板（CALIBRATE: 对应 flag_*.png，用于识别并点击所选国家）
FLAG_TEMPLATES: Dict[Country, str] = {
    Country.RED: "flag_red.png",
    Country.BLUE: "flag_blue.png",
    Country.YELLOW: "flag_yellow.png",
}

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
    def __init__(self, capturer, vision, controller, config: RuntimeConfig, store=None):
        self.capturer = capturer
        self.vision = vision
        self.controller = controller
        self.config = config
        self.store = store

    def _ctx(self) -> Context:
        return Context(
            capturer=self.capturer,
            vision=self.vision,
            controller=self.controller,
            config=self.config,
            store=self.store,
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
            # 异常兜底：忽略 ROI 全屏重扫一次
            pos = find_target(ctx.frame, replace(target, roi=None), ctx.vision)
        if pos is None:
            report_problem(ctx.frame, ctx.vision, f"未找到目标 {target.name!r}", name="lifecycle")
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
        pos = find_target(ctx.frame, target, ctx.vision)
        if pos is None:
            # 异常兜底：忽略 ROI 全屏重扫一次
            pos = find_target(ctx.frame, replace(target, roi=None), ctx.vision)
        if pos is None:
            report_problem(ctx.frame, ctx.vision, f"未找到目标 {target.name!r}", name="lifecycle")
        return pos

    def _wait_for_state(
        self,
        ctx: Context,
        state: GameState,
        timeout: float = 15.0,
        interval: float = 0.5,
        candidates: Optional[Tuple[GameState, ...]] = None,
    ) -> bool:
        """抓帧轮询直到 observe_state 命中 state；超时/抓帧失败返回 False。"""
        deadline = time.monotonic() + timeout
        while ctx.running and time.monotonic() < deadline:
            try:
                frame = ctx.capturer.grab()
            except Exception as exc:
                logger.warning("等待状态 %s 时抓帧失败: %s", state.name, exc)
                return False
            ctx.frame = frame
            observed = observe_state(
                frame,
                ctx.vision,
                candidates=candidates,
                store=ctx.store,
                config=ctx.config,
            )
            if observed == state:
                ctx.last_state = observed
                return True
            time.sleep(interval)
        logger.warning("等待状态 %s 超时", state.name)
        # 诊断：打印超时瞬间的画面 OCR 全文，便于校准签名/模板
        try:
            if ctx.frame is not None:
                details = ctx.vision.read_all(ctx.frame)
                logger.warning(
                    "等待状态 %s 超时，当前画面识别结果（共 %d 条）:",
                    state.name, len(details),
                )
                for text, conf, center in details:
                    logger.warning("    '%s' (%.2f) @ %s", text, conf, center)
        except Exception as exc:
            logger.warning("等待状态 %s 超时后打印画面失败: %s", state.name, exc)
        return False

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
    def __init__(self, capturer, vision, controller, config: RuntimeConfig, store=None):
        super().__init__(capturer, vision, controller, config, store)
        self.running = True
        self.create_count = 0
        self.language_initialized = False
        self.hide_stall_initialized = False
        self.account: Dict[str, str] = {"username": "", "password": "", "email": ""}
        self.used_usernames: set = set()
        self._register_fields_filled = False
        self._login_form_done = False
        self._consecutive_failures = 0

    # ------------------------------------------------------------------
    # 全局一次性设置（游戏记忆，整个生命周期只执行一次）
    # ------------------------------------------------------------------
    def run(self):
        logger.info("OuterLifecycle 启动")
        # TITLE 状态第一步：切换默认语言，是后续中文 OCR 识别的基础。
        if not self.change_default_language():
            logger.error("语言初始化失败，后续中文识别可能不可用，请检查 language.png")

        # 诊断：打印当前画面识别到的状态与 OCR 全文，便于定位「停在启动」时屏幕在哪
        self._log_current_state()

        while self.running:
            # 每个角色周期只生成一次账号；重试（register/login/create 失败后 continue）
            # 复用同一个账号，避免因状态检测失败而每轮换新用户名死循环。
            if not self.account["username"]:
                self._generate_account()
            logger.info("开始第 %d 次角色创建", self.create_count + 1)

            failed_step = None
            if not self.register():
                failed_step = "register"
            elif not self.login():
                failed_step = "login"
            elif not self.create_character():
                failed_step = "create_character"

            if failed_step is not None:
                self._consecutive_failures += 1
                logger.error(
                    "第 %d 次连续失败（步骤=%s）",
                    self._consecutive_failures, failed_step,
                )
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error("连续失败 %d 次，终止外层循环", self._consecutive_failures)
                    self.running = False
                continue

            self._consecutive_failures = 0
            self.enter_game()
            self.create_count += 1
            # CALIBRATE: 目前不识别「用户名已存在」提示，成功后清空账号让下一角色生成新号。
            # 若要碰撞后换号，需在 register() 内识别游戏「用户名已存在」文案再决定是否重新生成。
            self.account["username"] = ""
            if self.create_count >= 5:
                # CALIBRATE: 任务号每个账号 5 个角色用完启用新任务号
                self.create_count = 0
                logger.info("本任务号 5 个角色已用完，应切换新任务号")

    # ------------------------------------------------------------------
    # 修改默认语言（只执行一次，TITLE 状态第一步）
    # ------------------------------------------------------------------
    def change_default_language(self) -> bool:
        if self.language_initialized:
            return True
        ctx = self._ctx()
        try:
            frame = self.capturer.grab()
        except Exception as exc:
            logger.error("初始化语言：抓帧失败: %s", exc)
            return False
        ctx.frame = frame
        # 用 language.png 模板定位语言按钮并点击，切换到中文。
        # 这是后续所有中文状态签名识别的基础，必须在注册流程前完成。
        ok = self._click_target(
            ctx,
            Target(
                name="语言按钮",
                kind="template",
                template_path="language.png",
                threshold=0.8,
                roi=(1919,100,35,45)
            ),
        )
        if ok:
            self.language_initialized = True
            logger.info("语言已切换为默认（中文）")
        return ok

    # ------------------------------------------------------------------
    # 诊断：打印当前画面状态 + OCR 全文
    # ------------------------------------------------------------------
    def _log_current_state(self) -> None:
        try:
            frame = self.capturer.grab()
        except Exception as exc:
            logger.error("诊断抓帧失败: %s", exc)
            return
        observed = observe_state(
            frame, self.vision, store=self.store, config=self.config
        )
        logger.info("当前识别状态: %s", observed.name if observed else "未知")
        if observed is None:
            try:
                details = self.vision.read_all(frame)
                logger.warning("当前画面 OCR 全文（共 %d 条）:", len(details))
                for text, conf, center in details:
                    logger.warning("    '%s' (%.2f) @ %s", text, conf, center)
            except Exception as exc:
                logger.warning("诊断 OCR 失败: %s", exc)

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
    # 注册：TITLE -> CHECK_IN -> LOG_IN
    # ------------------------------------------------------------------
    def _generate_account(self) -> None:
        """生成新账号：随机用户名（会话内不重复）+ 固定密码/邮箱，记忆供登录复用。"""
        while True:
            username = f"task{random.randint(100000, 999999)}"
            if username not in self.used_usernames:
                self.used_usernames.add(username)
                break
        self.account = {
            "username": username,
            "password": "12345678",   # 默认密码（连续两次：密码 + 确认密码）
            "email": "1111@qq.com",   # 固定邮箱
        }
        logger.info(
            "生成新账号: 用户名=%s 密码=%s 邮箱=%s",
            self.account["username"], self.account["password"], self.account["email"],
        )

    def register(self) -> bool:
        ctx = self._ctx()
        self._register_fields_filled = False
        self._register_clicked = False

        def click_register(c: Context) -> bool:
            # TITLE -> 点击注册按钮进入注册页 CHECK_IN（一次性，避免页面加载期间重复点击）
            if self._register_clicked:
                return True
            if not self._click_target(
                c, Target(name="注册按钮", kind="template",
                          template_path="checkin.png", threshold=0.6,roi=(1919,278,442,72))
            ):
                return False
            self._register_clicked = True
            return True

        def fill_and_submit(c: Context) -> bool:
            # CHECK_IN -> 填表（幂等）并提交（Enter），成功后进入 LOG_IN
            if not self._fill_register_form(c):
                return False
            return self._submit_and_verify(c)

        fsm = StateMachine(
            {
                GameState.TITLE: [
                    Transition(GameState.CHECK_IN, action=click_register),
                ],
                GameState.CHECK_IN: [
                    Transition(GameState.LOG_IN, action=fill_and_submit),
                ],
            },
            name="register",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx, stop_state=GameState.LOG_IN)
        return ctx.last_state == GameState.LOG_IN

    # ------------------------------------------------------------------
    # 注册页表单填写（Tab 切换字段）
    # ------------------------------------------------------------------
    def _fill_register_form(self, c: Context) -> bool:
        # 表单字段只填一次；协议勾选失败重试时不再重复输入，避免污染已填内容。
        if not self._register_fields_filled:
            # 1) 点击用户名输入框（模板 username.png），粘贴用户名
            if not self._click_target(
                c, Target(name="用户名输入框", kind="template", template_path="username.png", threshold=0.8,roi=(500,300,920,480))
            ):
                return False
            self.controller.paste_text(self.account["username"])

            # 2) tab -> 密码
            self.controller.key_press("tab")
            self.controller.paste_text(self.account["password"])

            # 3) tab -> 确认密码（默认密码连续输入两次）
            self.controller.key_press("tab")
            self.controller.paste_text(self.account["password"])

            # 4) tab -> 固定邮箱
            self.controller.key_press("tab")
            self.controller.paste_text(self.account["email"])

            # 5) end 键
            self.controller.key_press("end")
            self._register_fields_filled = True

        # 6) 根据 box.png 定位并勾选两个用户协议
        if not self._agree_to_terms(c):
            return False

        # 提交改由 _submit_and_verify 按 Enter 完成（见 register() 的 fill_and_submit）。
        return True

    def _agree_to_terms(self, c: Context) -> bool:
        # box.png 为纯「同意用户协议」勾选框模板（未勾选态）；两个协议各一个勾选框。
        # 用新鲜帧（避免填表前的旧帧），并按分数降序 + NMS 去重后取前 2 个真实勾选框。
        try:
            frame = c.capturer.grab()
        except Exception as exc:
            logger.warning("勾选协议抓帧失败: %s", exc)
            return False
        c.frame = frame

        matches = c.vision.find_template_all(frame, "box.png", threshold=0.6)
        if not matches:
            report_problem(frame, c.vision, "未找到用户协议勾选框 (box.png)", name="register")
            return False

        matches.sort(key=lambda m: m[1], reverse=True)
        kept: List[Tuple[Tuple[int, int], float]] = []
        for corners, score in matches:
            cx = sum(p[0] for p in corners) // len(corners)
            cy = sum(p[1] for p in corners) // len(corners)
            if any(abs(cx - kx) < 8 and abs(cy - ky) < 8 for (kx, ky), _ in kept):
                continue
            kept.append(((cx, cy), score))
            if len(kept) >= 2:
                break

        if len(kept) < 2:
            logger.warning("只找到 %d 个勾选框，需确认第二个协议位置（CALIBRATE）", len(kept))
        for (cx, cy), score in kept:
            logger.info("勾选用户协议 @ (%d, %d), score=%.3f", cx, cy, score)
            c.controller.click(cx, cy)
        return True

    def _submit_and_verify(self, c: Context) -> bool:
        """按 Enter 提交注册，等待进入 LOG_IN；识别注册失败则换号重填。"""
        self.controller.key_press("enter")
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                frame = c.capturer.grab()
            except Exception as exc:
                logger.warning("提交注册后抓帧失败: %s", exc)
                return False
            c.frame = frame
            observed = observe_state(
                frame, c.vision,
                candidates=(GameState.LOG_IN,),
                store=c.store, config=c.config,
            )
            if observed == GameState.LOG_IN:
                return True
            # 识别「用户名已存在 / 注册失败」等弹窗，命中则换号并允许下轮重填
            if self._detect_register_failure(frame):
                logger.warning("注册失败（用户名冲突/失败提示），重新生成账号")
                self._generate_account()
                self._register_fields_filled = False
                return False
            time.sleep(0.5)
        logger.warning("提交注册后等待进入 LOG_IN 超时")
        return False

    def _detect_register_failure(self, frame) -> bool:
        """OCR 识别注册失败关键词（用户名已存在 / 注册失败等）。"""
        # CALIBRATE: 关键词为占位，需实机确认注册失败弹窗文案。
        keywords = ("已存在", "注册失败", "失败")
        for text, _conf, _center in self.vision.read_all(frame):
            norm = normalize_text(text)
            if any(kw in norm for kw in keywords):
                return True
        return False

    # ------------------------------------------------------------------
    # 登录： LOG_IN ->（选频道）-> 填账号密码 -> alarm_window -> CREATE_ROLE
    # ------------------------------------------------------------------
    def _select_channel(self, c: Context) -> bool:
        # 若不在频道选择页，先点击 Channel.png 进入；再点一个 Kanal 回到登录页。
        observed = observe_state(
            c.frame, c.vision,
            candidates=(GameState.CHANNEL_SELECT,),
            store=c.store, config=c.config,
        )
        if observed != GameState.CHANNEL_SELECT:
            if not self._click_target(
                c, Target(name="频道选择", kind="template", template_path="Channel.png", threshold=0.6)
            ):
                return False
            if not self._wait_for_state(c, GameState.CHANNEL_SELECT, candidates=(GameState.CHANNEL_SELECT,)):
                return False
        channel = random.choice([f"Kanal {i}" for i in range(1, 6)])
        logger.info("随机选择频道: %s", channel)
        if not self._click_target(c, Target(name="目标频道", kind="ocr", text=channel, fuzzy=True)):
            return False
        return self._wait_for_state(c, GameState.LOG_IN, candidates=(GameState.LOG_IN,))

    def _wait_login_result(self, c: Context, alarm_timeout: float = 30.0, total_timeout: float = 120.0) -> bool:
        """登录提交后等待进入 CREATE_ROLE。

        alarm_window.png 持续 alarm_timeout 无变化时，向用户反馈并询问是否重试，
        避免无限等待（用户选择不重试则终止）。
        """
        deadline = time.monotonic() + total_timeout
        alarm_since = None
        while c.running and self.running and time.monotonic() < deadline:
            try:
                frame = c.capturer.grab()
            except Exception as exc:
                logger.warning("等待登录结果抓帧失败: %s", exc)
                return False
            c.frame = frame
            observed = observe_state(
                frame, c.vision,
                candidates=(GameState.CREATE_ROLE,),
                store=c.store, config=c.config,
            )
            if observed == GameState.CREATE_ROLE:
                c.last_state = observed
                return True

            hit, _, _ = c.vision.find_template_bbox(frame, "alarm_window.png", threshold=0.6)
            now = time.monotonic()
            if hit:
                if alarm_since is None:
                    alarm_since = now
                elif now - alarm_since >= alarm_timeout:
                    report_problem(frame, c.vision, "登录卡在 alarm_window 无变化", name="login")
                    try:
                        ans = input("程序出现问题：登录长时间无响应。是否重试？(y/n，默认 n): ").strip().lower()
                    except EOFError:
                        ans = "n"
                    if ans in ("y", "yes"):
                        logger.info("用户选择重试，继续等待登录")
                        alarm_since = now
                        continue
                    logger.info("用户选择不重试，终止")
                    self.running = False
                    c.running = False
                    return False
            else:
                alarm_since = None
            time.sleep(0.5)
        logger.warning("等待登录结果超时")
        return False

    def login(self) -> bool:
        ctx = self._ctx()
        self._login_channel_selected = False
        self._login_form_done = False

        def do_login(c: Context) -> bool:
            if self._login_form_done:
                return True
            # 1) 先选频道（一次）
            if not self._login_channel_selected:
                if not self._select_channel(c):
                    return False
                self._login_channel_selected = True
                return True
            # 2) 填账号密码并提交
            if not self._click_target(
                c, Target(name="账号输入框", kind="template", template_path="account.png", threshold=0.6)
            ):
                return False
            self.controller.paste_text(self.account["username"])
            self.controller.key_press("tab")
            self.controller.paste_text(self.account["password"])
            self.controller.key_press("enter")
            # 3) 等待登录结果（alarm_window -> CREATE_ROLE）
            if not self._wait_login_result(c):
                return False
            self._login_form_done = True
            return True

        fsm = StateMachine(
            {
                GameState.LOG_IN: [
                    Transition(GameState.CREATE_ROLE, action=do_login),
                ],
            },
            name="login",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx, stop_state=GameState.CREATE_ROLE)
        return ctx.last_state == GameState.CREATE_ROLE

    # ------------------------------------------------------------------
    # 创建角色：CREATE_ROLE -> COUNTRY_SELECT -> LOADING -> MENU
    # ------------------------------------------------------------------
    def create_character(self) -> bool:
        ctx = self._ctx()

        def do_select_class(c: Context) -> bool:
            # CALIBRATE: 创建角色页选战士（OCR 识别名「战士」），进入国家选择页。
            self.controller.click(*POS_WARRIOR_CLASS)
            return True

        def do_bind_country(c: Context) -> bool:
            # 国家选择页（「选择你的帝国」）：识别并点击所选国家国旗。
            return self._bind_country(c)

        fsm = StateMachine(
            {
                GameState.CREATE_ROLE: [
                    Transition(GameState.COUNTRY_SELECT, action=do_select_class),
                ],
                GameState.COUNTRY_SELECT: [
                    Transition(GameState.LOADING, action=do_bind_country),
                ],
            },
            name="create_character",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx, stop_state=GameState.MENU)
        return ctx.last_state == GameState.MENU

    def _bind_country(self, ctx: Context) -> bool:
        # 国家选择页：用国旗模板定位并点击用户选择的国家。
        # CALIBRATE: flag_*.png 为整屏/卡片的国旗截图，模板匹配后点击其中心；
        # 若点击中心无效，需实机校准为国旗卡片的精确点击点。
        flag = FLAG_TEMPLATES[self.config.country]
        return self._click_target(
            ctx,
            Target(
                name=f"国家旗帜-{self.config.country.value}",
                kind="template",
                template_path=flag,
                threshold=0.6,
            ),
        )

    # ------------------------------------------------------------------
    # 进入游戏内部循环
    # ------------------------------------------------------------------
    def enter_game(self):
        logger.info("进入游戏")
        game_loop = GameLifecycle(
            self.capturer, self.vision, self.controller, self.config, self.store
        )
        game_loop.run()


# ===========================================================================
# 内层生命周期：游戏内从主菜单到交易完整流程
# ===========================================================================
class GameLifecycle(_LifecycleBase):
    def __init__(self, capturer, vision, controller, config: RuntimeConfig, store=None):
        super().__init__(capturer, vision, controller, config, store)
        # 每角色一次（新角色需要；游戏会记忆的设置不在这里）
        self.equip_weapon_done = False
        self.auto_potion_done = False
        self.templates_initialized = False

    def run(self):
        ctx = self._ctx()
        if not self._initialize_templates(ctx):
            return
        fsm = StateMachine(
            self._table(),
            name="game",
            timeout=self.config.timeout,
            max_attempts=self.config.max_attempts,
        )
        fsm.run(ctx)

    # ------------------------------------------------------------------
    # 首次循环初始化：用内置图片全屏搜索游戏内 UI（置信度 > 0.6），记录四点坐标
    # ------------------------------------------------------------------
    def _initialize_templates(self, ctx: Context) -> bool:
        if self.templates_initialized:
            return True
        self.templates_initialized = True
        if self.store is None:
            return True

        frame = None
        try:
            frame = ctx.capturer.grab()
        except Exception as exc:
            logger.error("[game] 初始化模板抓帧失败: %s", exc)
            ctx.running = False
            return False
        ctx.frame = frame

        for state, sigs in TEMPLATE_SIGNATURES.items():
            # 只初始化游戏内模板；跳过游戏外状态（TITLE/CHECK_IN/LOG_IN 的模板
            # 只在标题/注册/登录页出现，游戏内不存在，会误判为失败）。
            if state in (GameState.TITLE, GameState.CHECK_IN, GameState.LOG_IN):
                continue
            for sig in sigs:
                path = resolve_template_path(sig.template_path, self.config)
                key = self.store.template_key(path)
                if key in self.store.template_boxes:
                    continue  # 已学习，跳过
                hit, corners, score = self.vision.find_template_bbox(
                    frame, path, threshold=sig.threshold
                )
                if not hit:
                    report_problem(
                        frame, self.vision,
                        f"初始化模板 '{path}' 未命中（阈值 {sig.threshold}）",
                        name="game",
                    )
                    ctx.running = False
                    return False
                bbox = polygon_to_bbox(corners, margin=8)
                if bbox is not None:
                    self.store.template_boxes[key] = bbox
                    self.store.save()
                    logger.info(
                        "[game] 初始化模板 '%s' -> 四点坐标=%s (bbox=%s, score=%.3f)",
                        path, corners, bbox, score,
                    )
        return True

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
