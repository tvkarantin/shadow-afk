from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

STAGES = [
    ("LOBBY", "Лобби", "Профиль «Отряды»"),
    ("MATCHMAKING", "Поиск матча", "Подключение команды"),
    ("LOADING", "Загрузка", "Смена карты и интерфейса"),
    ("WAITING_FOR_PLAYERS", "Ожидание игроков", "Команда загружается"),
    ("BATTLE_BUS", "Боевой автобус", "Матч начинается"),
    ("IN_MATCH", "В матче", "Команда в игре"),
    ("ELIMINATED", "Выбывание", "Игрок выбыл, матч ещё идёт"),
    ("SPECTATING", "Наблюдение", "Союзники продолжают бой"),
    ("RESULTS", "Результаты", "Команда завершила матч"),
    ("RETURNING_TO_LOBBY", "Возврат в лобби", "Цикл завершается"),
]
LABELS = {key: (title, hint) for key, title, hint in STAGES}
LABELS.update(GAME_NOT_FOUND=("Игра не найдена", "Выберите окно Fortnite"),
              ERROR=("Захват недоступен", "Проверьте, что окно игры открыто"))
TRANSITIONS = {
    "GAME_NOT_FOUND": set(LABELS) - {"ERROR"},
    "ERROR": set(LABELS),
    "LOBBY": {"MATCHMAKING", "LOADING", "WAITING_FOR_PLAYERS", "BATTLE_BUS", "IN_MATCH"},
    "MATCHMAKING": {"LOBBY", "LOADING", "WAITING_FOR_PLAYERS", "BATTLE_BUS", "IN_MATCH"},
    "LOADING": {"LOBBY", "WAITING_FOR_PLAYERS", "BATTLE_BUS", "IN_MATCH"},
    "WAITING_FOR_PLAYERS": {"LOBBY", "BATTLE_BUS", "IN_MATCH"},
    "BATTLE_BUS": {"IN_MATCH", "ELIMINATED", "SPECTATING", "RESULTS", "LOBBY"},
    "IN_MATCH": {"ELIMINATED", "SPECTATING", "RESULTS", "LOBBY"},
    "ELIMINATED": {"SPECTATING", "IN_MATCH", "RESULTS", "LOBBY"},
    "SPECTATING": {"IN_MATCH", "ELIMINATED", "RESULTS", "LOBBY"},
    "RESULTS": {"RETURNING_TO_LOBBY", "LOBBY"},
    "RETURNING_TO_LOBBY": {"LOBBY", "MATCHMAKING", "LOADING"},
}


@dataclass
class Match:
    state: str = "GAME_NOT_FOUND"
    pending: str = ""
    confirmations: int = 0
    started: float | None = None
    detected: int = 0
    completed: int = 0
    match_seconds: float = 0
    spectating_seconds: float = 0
    changed_at: float = 0

    def observe(self, candidate, now, required=3):
        allowed = TRANSITIONS[self.state] | {"GAME_NOT_FOUND", "ERROR"}
        if not candidate or candidate == self.state or candidate not in allowed:
            self.pending, self.confirmations = "", 0
            return False
        if candidate != self.pending:
            self.pending, self.confirmations = candidate, 0
        self.confirmations += 1
        if self.confirmations < required:
            return False
        if self.state == "SPECTATING":
            self.spectating_seconds += now - self.changed_at
        self.state, self.changed_at = candidate, now
        self.pending, self.confirmations = "", 0
        if candidate in {"BATTLE_BUS", "IN_MATCH", "ELIMINATED", "SPECTATING"} and self.started is None:
            self.started = now
            self.detected += 1
        if candidate == "RESULTS" and self.started is not None:
            self.match_seconds += now - self.started
            self.completed += 1
            self.started = None
        if candidate in {"LOBBY", "GAME_NOT_FOUND", "ERROR"}:
            self.started = None
        return True


def load_gray(path):
    frame = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if frame is None:
        raise ValueError("Не удалось открыть изображение")
    return frame


def recognize(frame, templates, threshold):
    height, width = frame.shape
    factor = min(1.0, 960 / width)
    if factor < 1:
        frame = cv2.resize(frame, (round(width * factor), round(height * factor)), interpolation=cv2.INTER_AREA)
    scores = {}
    for state, pattern, reference_width in templates:
        for adjustment in (0.9, 1.0, 1.1):
            scale = width / reference_width * adjustment * factor
            w, h = (round(size * scale) for size in reversed(pattern.shape))
            if min(w, h) < 6 or w > frame.shape[1] or h > frame.shape[0]:
                continue
            sample = cv2.resize(pattern, (w, h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            if sample.std() < 2:
                continue
            _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(frame, sample, cv2.TM_CCOEFF_NORMED))
            if score > scores.get(state, (-1, None))[0]:
                scores[state] = (score, tuple(round(v / factor) for v in (x, y, w, h)))
    ranked = sorted(((score, state, box) for state, (score, box) in scores.items()), reverse=True)
    if not ranked:
        return "", 0, None
    score, state, box = ranked[0]
    if score < threshold or (len(ranked) > 1 and score - ranked[1][0] < 0.03):
        return "", max(0, score), None
    return state, score, box
