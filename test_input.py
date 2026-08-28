# test_input.py

from vnc_vision import ScreenCapturer
from input_controller import InputController

capturer = ScreenCapturer(...)
controller = InputController(capturer)

controller.click(959, 591)