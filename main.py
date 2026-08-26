from vncdotool import api
import time
import os
import sys
import vnc_vision


VNC_HOST = "127.0.0.1"   # 这里输入 VNC Server 的 IP
VNC_PORT = 5900              # 默认 VNC 端口
VNC_PASSWORD = "123456"     #这里输入 VNC Server 的密码

EXPECTED_SIZE = (1026, 771)

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

        print(

            f"⚠️ 屏幕分辨率与预期不一致 "

            f"(预期 {EXPECTED_SIZE[0]} × {EXPECTED_SIZE[1]})"

        )

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

        client.captureScreen(SCREENSHOT_PATH)

        if os.path.exists(SCREENSHOT_PATH):

            file_size = os.path.getsize(SCREENSHOT_PATH)

            print("✅ 截图成功")

            print(f"文件: {SCREENSHOT_PATH}")

            print(f"大小: {file_size} bytes")

            return True

        print("❌ 截图命令执行完成，但没有找到文件")

        return False

    except Exception as e:

        print("❌ 截图失败")

        print(f"错误类型: {type(e).__name__}")

        print(f"错误信息: {e}")

        return False

# =========================

# 主程序

# =========================

def main():

    print("\n")

    print("=" * 50)

    print("VNC 自动化环境测试")

    print("=" * 50)

    client = connect_vnc()

    if client is None:

        print("\n程序终止：VNC 尚未连接成功")

        return 1

    try:

        print("\n[1/2] 检查屏幕")

        screen_ok = check_screen(client)

        if not screen_ok:

            print("\n⚠️ 当前环境暂不符合预期")

            print("仍然继续进行截图测试...")

        print("\n[2/2] 获取截图")

        screenshot_ok = capture_screen(client)

        if not screenshot_ok:

            print("\n❌ 核心测试失败")

            return 1

        print("\n" + "=" * 50)

        print("✅ VNC 核心链路测试完成")

        print("=" * 50)

        print("\n下一步：")

        print("1. 打开 screen_test.png")

        print("2. 确认是否为虚拟机实际画面")

        print("3. 确认画面是否为 1026 × 771")

        print("4. 确认后再接入 OCR")

        return 0

    finally:

        client.disconnect()

        print("\nVNC 连接已关闭")

if __name__ == "__main__":

    sys.exit(main())