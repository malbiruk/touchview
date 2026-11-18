"""Bounded, time-based finger movement history for touchview."""

import math
from collections import deque


class TrailHistory:
    """Keep separate paths for each contact, even when a touch slot is reused."""

    def __init__(self, lifetime):
        self.lifetime = lifetime
        self.active = {}
        self.paths = {}
        self.serial = 0

    def begin(self, slot):
        self.serial += 1
        self.active[slot] = self.serial

    def end(self, slot):
        self.active.pop(slot, None)

    def clear(self):
        self.active.clear()
        self.paths.clear()

    def sample(self, slots, now):
        self.prune(now)
        if self.lifetime <= 0:
            return
        for slot, (x, y) in slots.items():
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            if slot not in self.active:
                self.begin(slot)
            key = self.active[slot]
            points = self.paths.setdefault(key, deque(maxlen=2048))
            # Stationary samples let a moving path fade while a finger rests,
            # without stretching its last edge. Zero-length edges aren't drawn.
            points.append((now, x, y))
        # Also bound memory during unusually rapid contact creation.
        while len(self.paths) > 128:
            del self.paths[next(iter(self.paths))]

    def prune(self, now):
        cutoff = now - self.lifetime
        for key in tuple(self.paths):
            points = self.paths[key]
            while points and points[0][0] <= cutoff:
                points.popleft()
            if not points:
                del self.paths[key]

    def segments(self, now):
        """Yield segment endpoints and their time-based fade multipliers."""
        self.prune(now)
        if self.lifetime <= 0:
            return
        for points in self.paths.values():
            previous = None
            for point in points:
                if previous is not None and previous[1:] != point[1:]:
                    age = max(0.0, now - point[0])
                    fade = max(0.0, 1.0 - age / self.lifetime) ** 1.5
                    if fade > 0:
                        yield previous[1:], point[1:], fade
                previous = point
