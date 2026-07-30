"""Version-controlled ATB table contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal

import pandas as pd


@dataclass(frozen=True, slots=True)
class TableContract:
    name: str
    fields: tuple[tuple[str, str], ...]

    @property
    def columns(self) -> list[str]:
        return [name for name, _ in self.fields]

    def empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                name: pd.Series(dtype=_pandas_dtype(field_type))
                for name, field_type in self.fields
            }
        )

    def frame(self, rows: list[dict[str, object]]) -> pd.DataFrame:
        if not rows:
            return self.empty_frame()
        frame = pd.DataFrame(rows)
        for column, field_type in self.fields:
            if column not in frame:
                frame[column] = None
            frame[column] = frame[column].astype(_pandas_dtype(field_type))
        return frame.loc[:, self.columns]


@dataclass(frozen=True, slots=True)
class AtbSchema:
    version: str
    source: str
    tables: dict[str, TableContract]


def load_atb_schema(version: str = "2025-05") -> AtbSchema:
    resource = files("ubio_autobox.projection.schemas") / f"atb-{version}.json"
    raw: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    return AtbSchema(
        version=str(raw["version"]),
        source=str(raw["source"]),
        tables={
            name: TableContract(
                name=name,
                fields=tuple((str(field[0]), str(field[1])) for field in fields),
            )
            for name, fields in raw["tables"].items()
        },
    )


def _pandas_dtype(
    field_type: str,
) -> Literal["string", "Int64", "Float64"]:
    if field_type == "string":
        return "string"
    if field_type == "int64":
        return "Int64"
    if field_type == "float64":
        return "Float64"
    raise ValueError(f"Unsupported ATB field type: {field_type}")
