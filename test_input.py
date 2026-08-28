# test_input.py

from vnc_vision import ScreenCapturer
from input_controller import InputController

capturer = ScreenCapturer("127.0.0.1", 5900, "123456")
controller = InputController(capturer)

controller.click(959, 591)