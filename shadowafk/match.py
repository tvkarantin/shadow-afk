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
LABELS["VICTORY"] = ("Королевская победа", "Шаблон баннера победы")
TRANSITIONS = {
    "UNKNOWN": set(LABELS) - {"VICTORY"},
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
    state: str = "UNKNOWN"
    previous: str = "UNKNOWN"
    match_id: int | None = None
    spectating_since: float | None = None
    last_confirmed: int = 0
    pending: str = ""
    confirmations: int = 0
    started: float | None = None
    detected: int = 0
    completed: int = 0
    match_seconds: float = 0
    spectating_seconds: float = 0
    changed_at: float = 0

    def observe(self, candidate, now, required=3):
        allowed = TRANSITIONS[self.state]
        if not candidate or candidate == self.state or candidate not in allowed:
            self.pending, self.confirmations = "", 0
            return False
        if candidate != self.pending:
            self.pending, self.confirmations = candidate, 0
        self.confirmations += 1
        if self.confirmations < required:
            return False
        self.suspend_spectating(now)
        self.previous = self.state
        self.state, self.changed_at = candidate, now
        self.last_confirmed = self.confirmations
        if candidate == "SPECTATING":
            self.spectating_since = now
        self.pending, self.confirmations = "", 0
        if candidate in {"BATTLE_BUS", "IN_MATCH", "ELIMINATED", "SPECTATING"} and self.started is None:
            self.started = now
            self.detected += 1
            self.match_id = self.detected
        if candidate == "RESULTS" and self.started is not None:
            self.match_seconds += now - self.started
            self.completed += 1
            self.started = None
        if candidate in {"RESULTS", "LOBBY"}:
            self.started = self.match_id = None
        return True


    def suspend_spectating(self, now):
        if self.spectating_since is not None:
            self.spectating_seconds += now - self.spectating_since
            self.spectating_since = None

    def interrupt(self, now):
        self.pending, self.confirmations = "", 0
        self.suspend_spectating(now)

    def spectating_total(self, now):
        return self.spectating_seconds + (now - self.spectating_since if self.spectating_since is not None else 0)


@dataclass(frozen=True)
class Pattern:
    state: str
    image: np.ndarray
    reference_width: int
    name: str = ""
    roi: tuple | None = None


@dataclass(frozen=True)
class Detection:
    state: str = ""
    confidence: float = 0
    box: tuple | None = None
    candidate: str = ""
    template: str = ""
    reason: str = ""


def load_gray(path):
    frame = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if frame is None:
        raise ValueError("Не удалось открыть изображение")
    return frame


def recognize(frame, templates, threshold):
    result = detect(frame, [Pattern(*item) for item in templates], threshold)
    return result.state, result.confidence, result.box if result.state else None


def detect(frame, templates, threshold, state_thresholds=None, current="", cancelled=None):
    height, width = frame.shape
    factor = min(1.0, 960 / width)
    if factor < 1:
        frame = cv2.resize(frame, (round(width * factor), round(height * factor)), interpolation=cv2.INTER_AREA)
    scores = {}
    for item in templates:
        state, pattern, reference_width = item.state, item.image, item.reference_width
        if pattern.ndim != 2 or not pattern.size or reference_width <= 0:
            continue
        fh, fw = frame.shape
        left, top, right, bottom = item.roi or (0, 0, 1, 1)
        x0, y0 = round(left * fw), round(top * fh)
        area = frame[y0:round(bottom * fh), x0:round(right * fw)]
        for adjustment in (0.9, 1.0, 1.1):
            if cancelled is not None and cancelled.is_set():
                return Detection(reason="Отменено")
            scale = width / reference_width * adjustment * factor
            w, h = (round(size * scale) for size in reversed(pattern.shape))
            if min(w, h) < 6 or w > area.shape[1] or h > area.shape[0]:
                continue
            sample = cv2.resize(pattern, (w, h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            if sample.std() < 2:
                continue
            _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(area, sample, cv2.TM_CCOEFF_NORMED))
            if score > scores.get(state, (-1, None))[0]:
                box = tuple(round(v / factor) for v in (x + x0, y + y0, w, h))
                scores[state] = (score, box, item.name)
    ranked = sorted(scores.items(), key=lambda item: item[1][0], reverse=True)
    if not ranked:
        return Detection(reason="Нет пригодных шаблонов для кадра")
    state, (score, box, name) = ranked[0]
    minimum = (state_thresholds or {}).get(state, threshold)
    if state == "VICTORY":
        minimum = max(0.95, minimum)
    minimum = max(0.5, minimum - 0.02) if state == current else minimum
    reason = ""
    if score < minimum:
        reason = "Совпадение ниже порога"
    elif len(ranked) > 1 and score - ranked[1][1][0] < (0.05 if current and state != current else 0.03):
        reason = "Неоднозначное совпадение"
    return Detection(state if not reason else "", max(0, score), box, state, name, reason)
