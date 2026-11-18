"""Domain exceptions. The global handler in main.py maps these to JSON responses."""


class DomainError(Exception):
    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class InvalidTransitionError(DomainError):
    status_code = 409
    code = "invalid_transition"


class SeparationOfDutiesError(DomainError):
    status_code = 403
    code = "separation_of_duties"


class ValidationFailure(DomainError):
    status_code = 400
    code = "validation_error"
