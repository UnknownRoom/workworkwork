# test_input.py
print("===== RUNNING NEW TEST_INPUT.PY =====")
import time
from vncdotool import api

from input_controller import InputController


# =========================
# VNC 配置
# =========================
VNC_HOST = "127.0.0.1"
VNC_PORT = 5900
VNC_PASSWORD = "123456"  # 如果你的 VNC 有密码，在这里填写


def main():
    print("正在连接 VNC...")

    client = api.connect(
        f"{VNC_HOST}::{VNC_PORT}",
        password=VNC_PASSWORD or None,
    )

    print("✅ VNC 连接成功")

    controller = InputController(client)

    # 给你 2 秒时间切换/确认远程游戏窗口
    print("2 秒后开始测试，请确保游戏的用户名输入框已经获得焦点...")
    time.sleep(2)

    test_text = "test123456"

    print(f"正在粘贴：{test_text}")

    controller.paste_text(test_text)

    print("✅ paste_text() 执行完成")
    print("请观察游戏用户名输入框是否出现：", test_text)

    # 不立即退出，方便观察 VNC
    time.sleep(3)

    client.disconnect()
    print("测试结束")


if __name__ == "__main__":
    main()
