from vncdotool import api
import time
import os
import sys
import vnc_vision
import cv2
from input_controller import InputController
from game_states import detect_game_state, GameState
from vnc_vision import VisionResult, OCRResult

VNC_HOST = "127.0.0.1"   # 这里输入 VNC Server 的 IP
VNC_PORT = 5900              # 默认 VNC 端口
VNC_PASSWORD = "123456"     #这里输入 VNC Server 的密码

EXPECTED_SIZE = (1920, 1080) # 预期的屏幕分辨率

SCREENSHOT_PATH = "screen_test.png"

# =========================

# VNC 连接

# =========================

def connect_vnc():

    """连接 VNC Server"""

    print("=" * 50)

    print("正在连接 VNC...")

    print(f"地址: {VNC_HOST}:{VNC_PORT}")

    try:

        client = api.connect(

            f"{VNC_HOST}::{VNC_PORT}",

            password=VNC_PASSWORD

        )

        print("✅ VNC 连接成功")

        return client

    except Exception as e:

        print("❌ VNC 连接失败")

        print(f"错误类型: {type(e).__name__}")

        print(f"错误信息: {e}")

        return None

# =========================

# 屏幕信息

# =========================

def check_screen(client):
    """检查远程屏幕尺寸"""
    try:
        width = client.screen.width
        height = client.screen.height
        print(f"远程屏幕尺寸: {width} × {height}")

        if (width, height) == EXPECTED_SIZE:
            print("✅ 屏幕分辨率符合预期")
            return True

        print(f"⚠️ 屏幕分辨率与预期不一致 "f"(预期 {EXPECTED_SIZE[0]} × {EXPECTED_SIZE[1]})")
        return False

    except Exception as e:
        print("❌ 无法获取远程屏幕信息")
        print(f"错误: {e}")
        return False

# =========================

# 截图

# =========================

def capture_screen(client):

    """获取远程屏幕截图"""

    print("正在获取屏幕截图...")

    try:

        # 使用已经验证成功的方式

        client.captureScreen(SCREENSHOT_PATH)

        if not os.path.exists(SCREENSHOT_PATH):

            print("❌ 截图命令执行完成，但没有找到文件")

            return None

        # 将截图文件读取为 OpenCV / NumPy 图像

        frame = cv2.imread(SCREENSHOT_PATH)

        if frame is None:

            print("❌ 截图文件存在，但 OpenCV 无法读取")

            return None

        print("✅ 截图成功")

        print(f"画面尺寸: {frame.shape[1]} × {frame.shape[0]}")

        return frame

    except Exception as e:

        print("❌ 截图失败")

        print(f"错误类型: {type(e).__name__}")

        print(f"错误信息: {e}")
        return None

# =========================
# 打印 VisionResult
# =========================

def print_vision_result(result: VisionResult):

    """输出 VisionResult，方便实机调试"""

    print("\n" + "=" * 50)

    print("VisionResult")

    print("=" * 50)

    print(f"OCR 结果数量: {len(result.ocr_results)}")

    if not result.ocr_results:

        print("  （没有识别到文本）")

    for item in result.ocr_results:

        print(

            f"  '{item.text}' "

            f"(置信度 {item.confidence:.2f}) "

            f"@ {item.position}"

        )
# =========================

# 状态测试

# =========================

def test_game_state(vision, frame):

    """
    测试：
    VisionEngine → VisionResult → GameState
    """

    print("\n[Vision] 正在分析当前画面...")

    result = vision.observe(frame)

    print_vision_result(result)

    state = detect_game_state(result)

    print("\n" + "=" * 50)

    print("GameState")

    print("=" * 50)

    if state is None:

        print("⚠️ 无法判断当前游戏状态")

    else:

        print(f"当前状态: {state.name}")

        print(f"状态值: {state.value}")

    return state
# =========================

# 主程序

# =========================

def main():

    client = connect_vnc()

    if client is None:
        print("\n程序终止：VNC 尚未连接成功")
        return 1
    
    capturer = vnc_vision.ScreenCapturer(client)
    controller = InputController(client)


    try:
        print("\n[1/3] 检查屏幕")
        client.refreshScreen(incremental=False)
        screen_ok = check_screen(client)

        if not screen_ok:
            print("\n⚠️ 当前环境暂不符合预期")
            print("仍然继续进行截图测试...")

        print("\n[2/3] 获取截图")

        frame = capture_screen(client)

        if frame is None:
            print("\n❌ 核心测试失败")
            return 1

        print("✅ VNC → NumPy 图像转换成功")

        print("\n[3/3] 初始化 Vision")

        vision = vnc_vision.VisionEngine(
            ocr_backend="paddleocr",
            languages=["ch"],
            gpu=False
        )

        print("✅ VisionEngine 初始化成功")

        # -------------------------
        # 4. 测试状态识别
        # -------------------------
        print("\n[4/4] 测试 GameState")

        state = test_game_state(vision, frame)

        print("\n" + "=" * 50)
        print("测试完成")
        print("=" * 50)

        if state is not None:
            print(f"✅ 当前识别状态: {state.name}")
        else:
            print("⚠️ 当前画面暂时无法匹配 State")
        return 0

    except Exception as e:

        print("\n❌ Vision 测试失败")

        print(f"错误类型: {type(e).__name__}")

        print(f"错误信息: {e}")

        return 1

    finally:

        start = time.perf_counter()

        frame = capture_screen(client)

        t1 = time.perf_counter()

        result = vision.observe(frame)

        t2 = time.perf_counter()

        state = detect_game_state(result)

        t3 = time.perf_counter()

        print(f"截图: {t1 - start:.3f}s")
        print(f"OCR:  {t2 - t1:.3f}s")
        print(f"状态: {t3 - t2:.3f}s")
        print(f"总计: {t3 - start:.3f}s")

        client.disconnect()

        print("\nVNC 连接已关闭")

if __name__ == "__main__":

    sys.exit(main())