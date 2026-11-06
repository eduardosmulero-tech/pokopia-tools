"""Errores e informes del formato de mod."""

from __future__ import annotations

from dataclasses import dataclass, field


class ModError(Exception):
    """El mod no se puede cargar, validar o aplicar. `exit_code` lo fija la CLI."""

    exit_code = 1

    def __init__(self, message: str, *, code: str = "mod", where: str = "",
                 details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.where = where
        self.details = details or {}

    def __str__(self) -> str:
        prefix = ("%s: " % self.where) if self.where else ""
        return prefix + super().__str__()


class GuardError(ModError):
    """Intento de escribir fuera de una copia (dump original, ruta protegida)."""

    exit_code = 2


class UsageError(ModError):
    """Falta un dato de invocacion o un fichero."""

    exit_code = 2


@dataclass
class Issue:
    severity: str          # "error" | "warning"
    code: str
    message: str
    where: str = ""

    def __str__(self) -> str:
        tag = "ERROR" if self.severity == "error" else "aviso"
        prefix = ("%s: " % self.where) if self.where else ""
        return "[%s] %s%s" % (tag, prefix, self.message)

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "where": self.where}


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def error(self, code: str, message: str, where: str = "") -> None:
        self.issues.append(Issue("error", code, message, where))

    def warning(self, code: str, message: str, where: str = "") -> None:
        self.issues.append(Issue("warning", code, message, where))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "Report") -> "Report":
        self.issues.extend(other.issues)
        return self

    def lines(self) -> list[str]:
        return [str(i) for i in self.issues]

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": len(self.errors),
                "warnings": len(self.warnings),
                "issues": [i.as_dict() for i in self.issues]}
