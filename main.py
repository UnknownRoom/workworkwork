from vncdotool import api
import time
import os
import sys
import vnc_vision
import cv2
from input_controller import InputController

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

# 主程序

# =========================

def main():

    client = connect_vnc()
    capturer = vnc_vision.ScreenCapturer(client)
    controller = InputController(client)

    if client is None:
        print("\n程序终止：VNC 尚未连接成功")
        return 1

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

        # 先直接识别整张屏幕
        results = vision.read_all(frame)

        print(f"\n检测到 {len(results)} 个文本：")

        for text, confidence, position in results:
            print(
                f"  '{text}' "
                f"(置信度 {confidence:.2f}) "
                f"@ {position}"
            )
            if text == "点击进入游戏" and confidence > 0.8:
                    capturer = InputController(client)
                        
                    x, y = position
                    controller.click(x, y)

                    print(f"✅ 找到目标，点击 ({x}, {y})")
                    break
            
        print("\n✅ VNC → Vision 测试完成")
        return 0

    except Exception as e:

        print("\n❌ Vision 测试失败")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")

        return 1

    finally:

        client.disconnect()

        print("\nVNC 连接已关闭")

if __name__ == "__main__":

    sys.exit(main())