import vnc_vision

from enum import Enum, auto

class GameState(Enum):
    UNKNOWN = auto()
    LOGIN = auto()
    LOBBY = auto()
    LOADING = auto()
    IN_GAME = auto()
    BATTLE = auto()
    REWARD = auto()
    DISCONNECTED = auto()
    ERROR = auto()