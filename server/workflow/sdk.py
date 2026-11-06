"""Plugin SDK: every card is a Plugin subclass and the frontend renders its form purely from the schema.

Input types: text / number / bool / select / json / list / any / code / workflow / agent / more_agent
Free-form inputs (text/number/json/list/code/any) are magic by default and stored as token arrays; pass magic=False to opt out in the workflow and can include magic variables; other inputs are stored as raw values.
"""
from dataclasses import dataclass, field
from typing import Any


MAGIC_TYPES = ("text", "number", "json", "list", "code", "any")


class StepError(Exception):
    """A card failed to run (the message is shown to the user as is)."""


@dataclass
class Input:
    name: str
    type: str = "text"
    label: str | None = None
    default: Any = None
    magic: bool | None = None  # None: on for free-form types (text/number/json/list/code/any)
    advanced: bool = False
    options: list | None = None  # select: ["a", "b"] or [{"value":..,"label":..}]
    multiline: bool = False
    placeholder: str = ""
    description: str = ""
    required: bool = False

    def __post_init__(self):
        if self.magic is None:
            self.magic = self.type in MAGIC_TYPES

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "default": self.default,
            "magic": self.magic,
            "advanced": self.advanced,
            "options": self.options,
            "multiline": self.multiline,
            "placeholder": self.placeholder,
            "description": self.description,
            "required": self.required,
        }


@dataclass
class Output:
    name: str
    type: str = "text"
    label: str | None = None
    default: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type, "label": self.label or self.name, "default": self.default}


class Plugin:
    id: str = ""
    name: str = ""
    icon: str = "puzzle"
    color: str = "gray"
    category: str = "Other"
    version: str = "1.0.0"
    description: str = ""
    inputs: list[Input] = []
    outputs: list[Output] = []
    requires_env: list[str] = []
    uses_agent_slot: bool = False  # if True, holds a global agent concurrency slot while running

    @classmethod
    def default_output(cls) -> str | None:
        for o in cls.outputs:
            if o.default:
                return o.name
        return cls.outputs[0].name if cls.outputs else None

    @classmethod
    def schema(cls) -> dict:
        return {
            "id": cls.id,
            "name": cls.name,
            "icon": cls.icon,
            "color": cls.color,
            "category": cls.category,
            "version": cls.version,
            "description": cls.description,
            "inputs": [i.to_dict() for i in cls.inputs],
            "outputs": [o.to_dict() for o in cls.outputs],
            "default_output": cls.default_output(),
            "requires_env": list(cls.requires_env),
            "container": False,
            "uses_agent_slot": cls.uses_agent_slot,
        }

    async def run(self, ctx, inputs: dict) -> dict:
        raise NotImplementedError
