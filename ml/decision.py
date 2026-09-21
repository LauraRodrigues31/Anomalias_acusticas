"""Lógica de decisão (N de M + cooldown + supressão do buzzer). Espelha decision.cpp."""
from collections import deque
from ml import config as C


class Decider:
    def __init__(self, n=C.VOTE_N, m=C.VOTE_M, cooldown_ms=C.COOLDOWN_MS):
        self.n, self.m, self.cooldown_ms = n, m, cooldown_ms
        self.hist = deque(maxlen=m)      # (pos, t_ms)
        self.cooldown_until = None

    def update(self, pos, now_ms, suppressed=False):
        """Retorna (alerta, t_primeira_positiva_ms). Janelas suprimidas são ignoradas."""
        if suppressed:
            return False, None
        self.hist.append((bool(pos), now_ms))
        npos = sum(1 for p, _ in self.hist if p)
        cool_ok = self.cooldown_until is None or now_ms >= self.cooldown_until
        if npos >= self.n and cool_ok:
            self.cooldown_until = now_ms + self.cooldown_ms
            first = next(t for p, t in self.hist if p)
            return True, first
        return False, None
