# -*- coding: utf-8 -*-
"""
有限状态机 (FSM) 自动化框架模板
适用于：游戏自动化、多角色生命周期管理、视觉驱动自动化

核心设计：
1. 状态与视觉解耦：采用 Mock 机制，实机视觉没通也不影响先调通主流程逻辑。
2. 每一个状态自带【超时保底机制 (Timeout Guard)】，超时自动按 R 键重试。
3. 全局上下文 (Context) 维护账号、角色 Index（1~5）、国家路线及共享接口。
"""

import time
import logging
import random
from enum import Enum, auto
from typing import Dict, Any, Optional

# ==========================================
# 0. 日志格式配置 (自动带上当前状态名称)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(state)s] %(message)s",
    datefmt="%H:%M:%S"
)

class LoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        kwargs["extra"] = {"state": self.extra.get("state_name", "SYS")}
        return msg, kwargs

logger = logging.getLogger("FSM")
sys_logger = LoggerAdapter(logger, {"state_name": "INIT"})


# ==========================================
# 1. 状态定义 (State Enum)
# ==========================================
class TaskState(Enum):
    INIT = auto()               # 01. 初始化运行环境与接口
    ACCOUNT_LOGIN = auto()      # 02. 账号注册 / 1~5 线随机选择登录
    CHARACTER_SELECT = auto()   # 03. 角色选择与创建 (武士职业)
    SETUP_CONFIG = auto()       # 04. 基础设置 (按 I 装备武器 / 自动药水 / 隐藏摆摊)
    MAIN_QUEST = auto()         # 05. 主线跑环 (地图寻路 / 打怪升级 / 交接任务)
    TEAM_FORMATION = auto()     # 06. 组队匹配 (前往防具商人与组队号组队)
    SELL_ITEMS = auto()         # 07. 清包出售 (防具商人出售装备药水变现约7800金)
    SWITCH_LINE_TRADE = auto()  # 08. 切线交易 (切至仓库号线路，前往复活点二次校验交易)
    SWITCH_CHARACTER = auto()   # 09. 角色/账号轮换 (单账号5角色循环/注册新账号)
    ERROR_RECOVERY = auto()     # 10. 异常恢复 (按 R 键缩小视角/地图防偏移重试)
    EXIT = auto()               # 11. 脚本退出


# ==========================================
# 2. 全局上下文 (Context)
# ==========================================
class Context:
    """维护全局运行数据，跨状态共享数据"""
    def __init__(self):
        self.account_id: str = "task_user_88"
        self.current_char_index: int = 1   # 当前处于第几个角色 (1~5)
        self.max_char_count: int = 5       # 单账号最大角色数
        self.country_id: int = 1          # 国家 ID (1, 2, 3 三国地图)
        self.target_line: int = 1         # 仓库号所在的交易线路
        
        # 视觉引擎与动作控制器句柄 (解耦)
        self.vision = MockVisionEngine()
        self.controller = MockController()
        
        self.run_status: bool = True

    def reset_char_state(self):
        """重置单角色上下文（如金币数、任务进度等）"""
        sys_logger.info("已重置角色临时状态数据。")


# ==========================================
# 3. 模拟视觉/动作接口 (Mock Interfaces)
# 作用：在实机视觉引擎未完全调试通过时，让状态机骨架能独立跑通
# ==========================================
class MockVisionEngine:
    def check_npc_visible(self, npc_name: str) -> bool:
        """检查 NPC 是否在视野中 (带名字识别防偏移)"""
        # 模拟 80% 的概率检测成功
        return random.random() > 0.2

    def check_trade_window(self) -> bool:
        return True

    def verify_id(self, target_id: str) -> bool:
        """校验玩家/仓库号/组队号 ID"""
        return True


class MockController:
    def press_key(self, key: str):
        sys_logger.info(f"[键鼠指令] 按下按键: {key.upper()}")

    def click(self, x: int, y: int):
        sys_logger.info(f"[键鼠指令] 点击坐标: ({x}, {y})")


# ==========================================
# 4. 状态机核心框架 (Finite State Machine)
# ==========================================
class FiniteStateMachine:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.current_state: TaskState = TaskState.INIT
        self.previous_state: Optional[TaskState] = None
        self.state_entry_time: float = time.time()
        
        # 每一个状态的超时保底配置 (秒)
        self.timeout_config: Dict[TaskState, float] = {
            TaskState.INIT: 10.0,
            TaskState.ACCOUNT_LOGIN: 60.0,
            TaskState.CHARACTER_SELECT: 30.0,
            TaskState.SETUP_CONFIG: 20.0,
            TaskState.MAIN_QUEST: 120.0,  # 寻路/打怪流程较长
            TaskState.TEAM_FORMATION: 45.0,
            TaskState.SELL_ITEMS: 30.0,
            TaskState.SWITCH_LINE_TRADE: 60.0,
            TaskState.SWITCH_CHARACTER: 30.0,
            TaskState.ERROR_RECOVERY: 15.0,
        }

    def change_state(self, new_state: TaskState):
        """执行状态转换并更新时间戳"""
        old_state_name = self.current_state.name
        self.previous_state = self.current_state
        self.current_state = new_state
        self.state_entry_time = time.time()
        
        logger_adapter = LoggerAdapter(logger, {"state_name": new_state.name})
        logger_adapter.info(f"状态转移: {old_state_name} ===> {new_state.name}")

    def is_timeout(self) -> bool:
        """检查当前状态是否停留超时"""
        limit = self.timeout_config.get(self.current_state, 30.0)
        return (time.time() - self.state_entry_time) > limit

    def run(self):
        """主循环分发驱动"""
        sys_logger.info("==========================================")
        sys_logger.info(">>> FSM 状态机主循环驱动启动 <<<")
        sys_logger.info("==========================================")
        
        while self.ctx.run_status:
            log_ctx = LoggerAdapter(logger, {"state_name": self.current_state.name})
            
            # 1. 检查状态超时与保底重试
            if self.is_timeout():
                log_ctx.warning(f"当前状态停留已超过阈值 ({self.timeout_config.get(self.current_state)}s)！触发异常恢复...")
                self.change_state(TaskState.ERROR_RECOVERY)
                continue

            # 2. 状态逻辑分发 (State Handler Dispatcher)
            try:
                if self.current_state == TaskState.INIT:
                    self.handle_init(log_ctx)
                elif self.current_state == TaskState.ACCOUNT_LOGIN:
                    self.handle_account_login(log_ctx)
                elif self.current_state == TaskState.CHARACTER_SELECT:
                    self.handle_character_select(log_ctx)
                elif self.current_state == TaskState.SETUP_CONFIG:
                    self.handle_setup_config(log_ctx)
                elif self.current_state == TaskState.MAIN_QUEST:
                    self.handle_main_quest(log_ctx)
                elif self.current_state == TaskState.TEAM_FORMATION:
                    self.handle_team_formation(log_ctx)
                elif self.current_state == TaskState.SELL_ITEMS:
                    self.handle_sell_items(log_ctx)
                elif self.current_state == TaskState.SWITCH_LINE_TRADE:
                    self.handle_switch_line_trade(log_ctx)
                elif self.current_state == TaskState.SWITCH_CHARACTER:
                    self.handle_switch_character(log_ctx)
                elif self.current_state == TaskState.ERROR_RECOVERY:
                    self.handle_error_recovery(log_ctx)
                elif self.current_state == TaskState.EXIT:
                    log_ctx.info("收到退出指令，结束状态机运行。")
                    self.ctx.run_status = False
            except Exception as e:
                log_ctx.error(f"捕获运行时异常: {e}，强制转入 ERROR_RECOVERY 恢复")
                self.change_state(TaskState.ERROR_RECOVERY)

            time.sleep(0.5)  # 主循环心跳间隔

    # ----------------------------------------------------
    # 各状态的具体业务逻辑 Handler
    # ----------------------------------------------------
    def handle_init(self, log):
        log.info("初始化 VNC 通道与视觉分析模块...")
        time.sleep(0.5)
        self.change_state(TaskState.ACCOUNT_LOGIN)

    def handle_account_login(self, log):
        line = random.randint(1, 5)
        log.info(f"随机选择线路 [{line} 线]，登录当前账号 [{self.ctx.account_id}]...")
        time.sleep(0.5)
        self.change_state(TaskState.CHARACTER_SELECT)

    def handle_character_select(self, log):
        log.info(f"选择/创建角色: 正在使用第 {self.ctx.current_char_index}/{self.ctx.max_char_count} 个角色 (职业: 武士)...")
        time.sleep(0.5)
        self.change_state(TaskState.SETUP_CONFIG)

    def handle_setup_config(self, log):
        log.info("进入游戏，执行初始化配置...")
        self.ctx.controller.press_key("i")  # 按 I 装备武器
        log.info("开启自动药水保护、设置隐藏摆摊")
        time.sleep(0.5)
        self.change_state(TaskState.MAIN_QUEST)

    def handle_main_quest(self, log):
        log.info(f"开启地图寻路与主线跑环流程 (当前国家: {self.ctx.country_id})...")
        npc_target = "新兵教官"
        
        # 防偏移机制：只有出现 NPC 名称才交互
        if self.ctx.vision.check_npc_visible(npc_target):
            log.info(f"【视觉确认】在屏幕中识别到 [{npc_target}] 名称，执行交互。")
            time.sleep(0.5)
            log.info("升至 3 级，完成战魂及杂货商人任务。")
            self.change_state(TaskState.TEAM_FORMATION)
        else:
            log.warning(f"【视觉提示】未在屏幕检测到 [{npc_target}] 名称，继续寻路等待...")
            time.sleep(0.5)

    def handle_team_formation(self, log):
        log.info("前往组队地点，检测组队号 ID 并发起组队请求...")
        time.sleep(0.5)
        self.change_state(TaskState.SELL_ITEMS)

    def handle_sell_items(self, log):
        log.info("前往防具商人，清空背包出售所有装备药品变现 (~7800 金币)...")
        time.sleep(0.5)
        self.change_state(TaskState.SWITCH_LINE_TRADE)

    def handle_switch_line_trade(self, log):
        log.info(f"切换线路至仓库号线路 ({self.ctx.target_line} 线)，前往复活点交易...")
        time.sleep(0.5)
        log.info("多次校验仓库号 ID 无误，交易确认完成。")
        self.change_state(TaskState.SWITCH_CHARACTER)

    def handle_switch_character(self, log):
        log.info(f"第 {self.ctx.current_char_index} 个角色完整生命周期结束。")
        if self.ctx.current_char_index < self.ctx.max_char_count:
            self.ctx.current_char_index += 1
            self.ctx.reset_char_state()
            log.info(f"轮换至下一个角色 (Index: {self.ctx.current_char_index})")
            self.change_state(TaskState.CHARACTER_SELECT)
        else:
            log.info("当前账号 5 个角色已全部用尽，准备切换/注册新账号...")
            self.change_state(TaskState.EXIT)

    def handle_error_recovery(self, log):
        log.warning("触发异常恢复机制: 按 R 键缩小游戏视角/地图，消除界面遮挡与路径偏移...")
        self.ctx.controller.press_key("r")
        time.sleep(1.0)
        
        target_state = self.previous_state if self.previous_state else TaskState.MAIN_QUEST
        log.info(f"异常恢复完毕，尝试返回上一个状态重新运行: {target_state.name}")
        self.change_state(target_state)


# ==========================================
# 5. 入口
# ==========================================
if __name__ == "__main__":
    context = Context()
    fsm = FiniteStateMachine(context)
    fsm.run()