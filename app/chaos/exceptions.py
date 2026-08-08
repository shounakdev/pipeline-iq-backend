class ChaosError(Exception):
    code = "CHAOS_ERROR"


class ChaosDisabledError(ChaosError):
    code = "CHAOS_ENGINE_DISABLED"


class ChaosValidationError(ChaosError):
    code = "CHAOS_REQUEST_REJECTED"


class ChaosExperimentNotFoundError(ChaosError):
    code = "CHAOS_EXPERIMENT_NOT_FOUND"


class ChaosRunNotFoundError(ChaosError):
    code = "CHAOS_RUN_NOT_FOUND"


class ChaosConflictError(ChaosError):
    code = "CHAOS_RUN_CONFLICT"


class ChaosKubernetesError(ChaosError):
    code = "CHAOS_KUBERNETES_ERROR"

class ChaosRunTimeoutError(ChaosError):
    code = "CHAOS_RUN_TIMEOUT"