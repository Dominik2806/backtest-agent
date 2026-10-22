"""Engine errors."""


class EngineError(Exception):
    """Base class of engine errors: bad inputs to the simulation."""


class EngineInvariantError(EngineError):
    """A rule of the engine was violated at run time (for example negative cash). Never expected with correct inputs."""
