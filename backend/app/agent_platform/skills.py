from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.agent_platform.contracts import canonical_json_object

SkillExecutor = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class SkillContractError(ValueError):
    """Raised when a Skill input or output violates its declared contract."""


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    version: str
    required_inputs: frozenset[str]
    output_fields: frozenset[str]
    executor: SkillExecutor


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> None:
        if definition.id in self._skills:
            raise SkillContractError(f"duplicate skill: {definition.id}")
        self._skills[definition.id] = definition

    def get(self, skill_id: str) -> SkillDefinition:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise SkillContractError(f"unknown skill: {skill_id}") from exc

    async def execute(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        definition = self.get(skill_id)
        try:
            normalized_payload = canonical_json_object(payload, label="skill input")
        except ValueError as exc:
            raise SkillContractError(str(exc)) from exc
        missing = definition.required_inputs - normalized_payload.keys()
        if missing:
            raise SkillContractError(f"missing skill inputs: {sorted(missing)}")
        result = definition.executor(normalized_payload)
        if inspect.isawaitable(result):
            result = await result
        try:
            result = canonical_json_object(result, label="skill output")
        except ValueError as exc:
            raise SkillContractError(str(exc)) from exc
        missing_output = definition.output_fields - result.keys()
        if missing_output:
            raise SkillContractError(f"missing skill outputs: {sorted(missing_output)}")
        return result
