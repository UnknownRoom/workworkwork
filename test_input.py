# test_input.py

from vnc_vision import ScreenCapturer
from input_controller import InputController

client = api.connect(

    "127.0.0.1::5900",

    password="123456"

)

controller = InputController(client)

controller.click(959, 591)

client.disconnect()
