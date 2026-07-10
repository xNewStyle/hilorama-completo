"""Modelos simples para manifiestos de actualizacion."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UpdateManifest:
    app: str
    latest_version: str
    min_required_version: str = ""
    download_url: str = ""
    sha256: str = ""
    size_bytes: int | None = None
    mandatory: bool = False
    notes: list[str] = field(default_factory=list)
    published_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "UpdateManifest":
        notes = data.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        return cls(
            app=str(data.get("app") or "HiloramaCliente"),
            latest_version=str(data.get("latest_version") or "").strip(),
            min_required_version=str(data.get("min_required_version") or "").strip(),
            download_url=str(data.get("download_url") or "").strip(),
            sha256=str(data.get("sha256") or "").strip().lower(),
            size_bytes=_safe_int(data.get("size_bytes")),
            mandatory=bool(data.get("mandatory", False)),
            notes=[str(item) for item in notes],
            published_at=str(data.get("published_at") or "").strip(),
        )

    def is_valid(self) -> bool:
        return bool(self.latest_version and self.download_url and self.sha256)


@dataclass
class UpdateCheckResult:
    ok: bool
    update_available: bool = False
    current_version: str = ""
    manifest: UpdateManifest | None = None
    error: str = ""


@dataclass
class DownloadResult:
    ok: bool
    file_path: str = ""
    sha256: str = ""
    error: str = ""


def _safe_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
