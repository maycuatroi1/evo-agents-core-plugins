"""The config of the core plugin jev and what it reads from it (``docs/jev-plugin.md``).

Every field is flat, because the hub's layers of config replace an object whole: a project that sets one threshold
must not lose the others. The key is an x-secret field, sealed on the hub and opened here, at the moment of a call.
A feature is off until the project sets it; ``model`` has no default, because the pinned version is the project's
choice and an alias (``jev-latest``) would let the vendor change the model under the project.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

SINK = "jev@typesafe"  # the egress sink of the manifest: the id a project's policy declares
SINK_KIND = "llm-backend"
HOST = "api.typesafe.ai"
DEFAULT_BASE_URL = f"https://{HOST}"
MODEL = r"^jev-[0-9]+\.[0-9]+\.[0-9]+$"  # a version id; an alias is refused
PRICE_PER_MILLION_USD = 0.042  # input tokens, as the vendor lists them
MODES = ("off", "suggest", "apply")
FEATURES = ("triage", "kg_review", "corrections", "rerank")
DEFAULT_THRESHOLD = 0.9  # starting points; a change to one is a decision (docs/jev-plugin.md)
DEFAULT_NOUL_NO = 0.1
DEFAULT_CAP = 50

SECRET = {"type": "string", "x-secret": True}


def _mode(title: str, what: str) -> dict:
    return {
        "title": title,
        "description": f"{what} off does nothing; suggest records what Jev answered for a person to read; apply also "
        "makes the change, an act of the plugin the hub lets a member undo.",
        "type": "string",
        "enum": list(MODES),
        "default": "off",
    }


def _threshold(title: str, what: str, default: float) -> dict:
    return {"title": title, "description": what, "type": "number", "minimum": 0, "maximum": 1, "default": default}


def _cap(title: str) -> dict:
    return {
        "title": title,
        "description": "The most acts this feature applies by itself in a day (UTC); past it the rest are only "
        "suggested.",
        "type": "integer",
        "minimum": 0,
        "default": DEFAULT_CAP,
    }


CONFIG = {
    "type": "object",
    "properties": {
        "api_key": {"title": "Jev API key", "description": "The key of the project's TypeSafe account.", **SECRET},
        "model": {
            "title": "Jev model version",
            "description": "The pinned version, jev-<major>.<minor>.<patch>. An alias is refused, and so is an "
            "answer from another model.",
            "type": "string",
            "pattern": MODEL,
        },
        "base_url": {
            "title": "Base URL",
            "description": "https only; every address it resolves to must be public, and the call is pinned to the "
            "address checked. Redirects are not followed.",
            "type": "string",
            "default": DEFAULT_BASE_URL,
        },
        "daily_usd": {
            "title": "Daily budget (USD)",
            "description": "What the project's calls may cost in a UTC day; the next call is refused once it would "
            "pass it.",
            "type": "number",
            "minimum": 0,
            "default": 1,
        },
        "triage_mode": _mode("Failure triage", "Reading why a run failed."),
        "triage_threshold": _threshold("Triage confidence", "The lowest confidence at which a cause is applied.", 0.9),
        "triage_cap": _cap("Triage acts a day"),
        "kg_review_mode": _mode("Graph review", "Deciding the items of the graph's review queue."),
        "kg_review_threshold": _threshold("Review confidence", "The lowest confidence of a choice to apply.", 0.9),
        "kg_review_noul_yes": _threshold("Review noul, yes", "A noul at or above this is a yes.", DEFAULT_THRESHOLD),
        "kg_review_noul_no": _threshold("Review noul, no", "A noul at or below this is a no.", DEFAULT_NOUL_NO),
        "kg_review_cap": _cap("Review acts a day"),
        "corrections_mode": _mode("Corrections", "Turning the corrections people made into rules."),
        "corrections_threshold": _threshold("Corrections confidence", "The lowest confidence to apply.", 0.9),
        "corrections_cap": _cap("Corrections acts a day"),
        "rerank": {
            "title": "Rerank",
            "description": "on lets the hub rank candidates with Jev; off leaves its own order.",
            "type": "string",
            "enum": ["off", "on"],
            "default": "off",
        },
    },
}


@dataclass(frozen=True)
class Settings:
    """What a project's effective config says, read once per call."""

    api_key: str | None
    model: str | None
    base_url: str
    daily_usd: float
    modes: Mapping[str, str]  # feature -> off, suggest, apply (rerank: off, on)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    @property
    def any_feature(self) -> bool:
        return any(mode != "off" for mode in self.modes.values())


def read(values: Mapping) -> Settings:
    """``Settings`` from the plugin's effective config."""
    modes = {name: str(values.get(f"{name}_mode") or "off") for name in ("triage", "kg_review", "corrections")}
    modes["rerank"] = str(values.get("rerank") or "off")
    return Settings(
        api_key=values.get("api_key") or None,
        model=values.get("model") or None,
        base_url=str(values.get("base_url") or DEFAULT_BASE_URL),
        daily_usd=float(values.get("daily_usd") if values.get("daily_usd") is not None else 1),
        modes=modes,
    )
