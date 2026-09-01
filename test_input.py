# test_input.py

from vncdotool import api
from input_controller import InputController

client = api.connect(

    "127.0.0.1::5900",

    password="123456"

)

controller = InputController(client)

controller.click(959, 591)
controller.key_press("end")

client.disconnect()
