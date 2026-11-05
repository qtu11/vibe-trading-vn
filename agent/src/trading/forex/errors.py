"""Structured failures safe to return without serializing broker credentials."""


class ForexError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    def payload(self) -> dict:
        return {"status": "error", "code": self.code, "error": str(self)}
