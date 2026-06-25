class MoveLockSet:

    def __init__(self):
        self._locked = set()

    def lock(self, from_sq, to_sq):
        self._locked.add((from_sq, to_sq))

    def is_locked(self, from_sq, to_sq):
        return (from_sq, to_sq) in self._locked

    def clear(self):
        self._locked.clear()

    def __contains__(self, key):
        return key in self._locked

    def __iter__(self):
        return iter(self._locked)

    def __len__(self):
        return len(self._locked)
