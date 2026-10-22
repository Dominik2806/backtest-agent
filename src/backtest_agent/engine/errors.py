"""Engine errors."""


class EngineError(Exception):
    """Base class of engine errors: bad inputs to the simulation."""


class EngineInvariantError(EngineError):
    """A rule of the engine was violated at run time (for example negative cash). Never expected with correct inputs."""


class InsufficientHistoryError(EngineError):
    """The provider delivered less history than the signal needs and ``allow_short_warmup`` is False.

    ``warmup`` is the ``WarmupInfo`` of the run.
    """

    def __init__(self, message: str, warmup: object = None) -> None:
        super().__init__(message)
        self.warmup = warmup


class InsufficientWarmupWarning(UserWarning):
    """The run continues with less history than the signal needs before the first decision (see ``WarmupInfo``)."""
