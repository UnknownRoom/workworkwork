from vncdotool import api

client = api.connect(
    "127.0.0.1::5900",
    password="你的VNC密码",
    timeout=30
)

print("VNC连接对象创建成功")

client.refreshScreen(incremental=False)

print("屏幕刷新成功")
print("屏幕尺寸:", client.screen.size)