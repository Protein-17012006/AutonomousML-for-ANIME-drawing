"""Framework-independent application errors mapped by inbound API adapters."""


class ServiceError(Exception):
    """Base class for expected application failures."""


class SessionNotFound(ServiceError):
    pass


class InvalidGapIndex(ServiceError):
    pass


class InvalidKeyImage(ServiceError):
    pass


class UnknownEngine(ServiceError):
    pass


class RuntimeBusy(ServiceError):
    pass
