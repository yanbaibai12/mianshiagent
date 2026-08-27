from __future__ import annotations

import copy
import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

agent_validator = importlib.import_module("scripts.validate_agent_definitions")
documentation_validator = importlib.import_module("scripts.validate_documentation")
deployment_validator = importlib.import_module("scripts.validate_deployment_contracts")
mcp_validator = importlib.import_module("scripts.validate_mcp_tools")
openapi_validator = importlib.import_module("scripts.validate_openapi_compatibility")
quality_gate = importlib.import_module("scripts.run_quality_gate")
secret_scan = importlib.import_module("scripts.run_secret_scan")
skill_validator = importlib.import_module("scripts.validate_skills")


class OpenApiContractHashTest(unittest.TestCase):
    def test_nested_referenced_schema_change_changes_contract_hash(self) -> None:
        schema = {
            "components": {
                "schemas": {
                    "Envelope": {
                        "type": "object",
                        "properties": {"payload": {"$ref": "#/components/schemas/Payload"}},
                    },
                    "Payload": {
                        "type": "object",
                        "properties": {"score": {"type": "integer"}},
                    },
                }
            }
        }
        contract = {"$ref": "#/components/schemas/Envelope"}

        before = openapi_validator._hash_schema_contract(contract, schema)
        schema["components"]["schemas"]["Payload"]["properties"]["score"]["type"] = "number"
        after = openapi_validator._hash_schema_contract(contract, schema)

        self.assertNotEqual(before, after)

    def test_json_pointer_escape_sequences_are_resolved(self) -> None:
        document = {"components": {"schemas": {"a/b~c": {"type": "string"}}}}

        resolved = openapi_validator._resolve_json_pointer(document, "#/components/schemas/a~1b~0c")

        self.assertEqual(resolved, {"type": "string"})

    def test_parameter_and_security_contract_changes_are_classified(self) -> None:
        schema = {
            "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
            "security": [{"bearerAuth": []}],
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "list_items",
                        "parameters": [
                            {
                                "name": "query",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        baseline = {"operations": openapi_validator._operation_contracts(schema)}

        optional_parameter_schema = copy.deepcopy(schema)
        optional_parameter_schema["paths"]["/items"]["get"]["parameters"].append(
            {
                "name": "page",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
            }
        )
        optional_failures = openapi_validator._compare(
            baseline,
            openapi_validator._operation_contracts(optional_parameter_schema),
        )

        required_parameter_schema = copy.deepcopy(schema)
        required_parameter_schema["paths"]["/items"]["get"]["parameters"].append(
            {
                "name": "Tenant",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            }
        )
        required_failures = openapi_validator._compare(
            baseline,
            openapi_validator._operation_contracts(required_parameter_schema),
        )

        security_schema = copy.deepcopy(schema)
        security_schema["components"]["securitySchemes"]["bearerAuth"]["scheme"] = "basic"
        security_failures = openapi_validator._compare(
            baseline,
            openapi_validator._operation_contracts(security_schema),
        )

        self.assertEqual(optional_failures, [])
        self.assertIn(
            {"operation": "GET /items", "reason": "required_parameter_added:header:tenant"},
            required_failures,
        )
        self.assertIn(
            {"operation": "GET /items", "reason": "security_sha256_changed"},
            security_failures,
        )


class OpenApiApprovedRemovalTest(unittest.TestCase):
    @staticmethod
    def approval_data(*, adr: str = "docs/adr/0002-retirement.md") -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "phase": "phase-1a-product-surface-retirement",
            "owner": "agent-platform-team",
            "adr": adr,
            "operations": [
                {
                    "method": "GET",
                    "path": "/retired",
                    "reason": "Retired after an approved product-surface review.",
                    "replacement": None,
                }
            ],
        }

    def test_exact_removed_operation_is_approved_and_partitioned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adr = root / "docs" / "adr" / "0002-retirement.md"
            adr.parent.mkdir(parents=True)
            adr.write_text("# Accepted retirement decision\n", encoding="utf-8")
            baseline = {"operations": {"GET /retired": {"operation_id": "retired"}}}

            approvals, errors = openapi_validator._validate_approved_removals(
                self.approval_data(),
                baseline=baseline,
                current={},
                root=root,
            )
            blocking, approved = openapi_validator._partition_approved_removals(
                [{"operation": "GET /retired", "reason": "operation_removed"}],
                approvals,
            )

        self.assertEqual(errors, [])
        self.assertEqual(blocking, [])
        self.assertEqual([item["operation"] for item in approved], ["GET /retired"])

    def test_unknown_operation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adr = root / "docs" / "adr" / "0002-retirement.md"
            adr.parent.mkdir(parents=True)
            adr.write_text("# Decision\n", encoding="utf-8")

            approvals, errors = openapi_validator._validate_approved_removals(
                self.approval_data(),
                baseline={"operations": {}},
                current={},
                root=root,
            )

        self.assertEqual(approvals, {})
        self.assertIn("approved_removals.operations[0].not_in_baseline:GET /retired", errors)

    def test_operation_that_still_exists_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adr = root / "docs" / "adr" / "0002-retirement.md"
            adr.parent.mkdir(parents=True)
            adr.write_text("# Decision\n", encoding="utf-8")
            operation = {"operation_id": "retired"}

            approvals, errors = openapi_validator._validate_approved_removals(
                self.approval_data(),
                baseline={"operations": {"GET /retired": operation}},
                current={"GET /retired": operation},
                root=root,
            )

        self.assertEqual(approvals, {})
        self.assertIn("approved_removals.operations[0].not_removed:GET /retired", errors)

    def test_missing_or_out_of_repository_adr_is_rejected(self) -> None:
        baseline = {"operations": {"GET /retired": {"operation_id": "retired"}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, missing_errors = openapi_validator._validate_approved_removals(
                self.approval_data(),
                baseline=baseline,
                current={},
                root=root,
            )
            _, traversal_errors = openapi_validator._validate_approved_removals(
                self.approval_data(adr="../outside.md"),
                baseline=baseline,
                current={},
                root=root,
            )

        self.assertIn("approved_removals.adr_file_missing", missing_errors)
        self.assertIn("approved_removals.adr_must_stay_within_repository", traversal_errors)

    def test_approval_does_not_exempt_non_removal_breaking_changes(self) -> None:
        approval = {
            "GET /retired": {
                "operation": "GET /retired",
                "owner": "agent-platform-team",
                "reason": "Approved retirement.",
                "replacement": None,
                "phase": "phase-1a-product-surface-retirement",
                "adr": "docs/adr/0002-retirement.md",
            }
        }
        failure = {
            "operation": "GET /retired",
            "reason": "required_parameter_added:header:tenant",
        }

        blocking, approved = openapi_validator._partition_approved_removals([failure], approval)

        self.assertEqual(blocking, [failure])
        self.assertEqual(approved, [])


class AgentRegistryValidationTest(unittest.TestCase):
    def test_active_agent_requires_real_entrypoint_and_valid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entrypoint = root / "backend" / "app" / "agents" / "resume_agent.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("def build_agent():\n    return object()\n", encoding="utf-8")
            data = {
                "schema_version": "1.0",
                "status": "active",
                "phase": "phase-1-runtime",
                "owner": "agent-platform-team",
                "agents": [
                    {
                        "id": "resume-rewrite-agent",
                        "version": "1.0.0",
                        "owner": "resume-intelligence-team",
                        "description": "Rewrites resumes from verified evidence.",
                        "entrypoint": "backend/app/agents/resume_agent.py:build_agent",
                        "allowed_tools": ["mcp.resume.read"],
                        "max_steps": 12,
                        "max_tokens": 24000,
                        "handoffs": [],
                    }
                ],
            }

            errors = agent_validator.validate_registry(data, root=root)

        self.assertEqual(errors, [])

    def test_agent_registry_rejects_invalid_semver_and_missing_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entrypoint = root / "agent.py"
            entrypoint.write_text("build_agent = object()\n", encoding="utf-8")
            data = {
                "schema_version": "1.0",
                "status": "active",
                "phase": "phase-1-runtime",
                "owner": "agent-platform-team",
                "agents": [
                    {
                        "id": "resume-agent",
                        "version": "v1",
                        "owner": " ",
                        "description": "Agent",
                        "entrypoint": "agent.py:build_agent",
                        "allowed_tools": ["bad tool"],
                        "max_steps": True,
                        "max_tokens": 0,
                        "handoffs": ["missing-agent"],
                    }
                ],
            }

            errors = agent_validator.validate_registry(data, root=root)

        self.assertTrue(any("version must be SemVer" in error for error in errors))
        self.assertTrue(any("symbol is not defined" in error for error in errors))
        self.assertTrue(any("max_steps must be a positive integer" in error for error in errors))
        self.assertTrue(any("allowed_tools[0] is invalid" in error for error in errors))
        self.assertTrue(any("references unknown agent: missing-agent" in error for error in errors))


class MCPRegistryValidationTest(unittest.TestCase):
    @staticmethod
    def active_registry() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "status": "active",
            "phase": "phase-2-shadow-runtime",
            "owner": "agent-platform-team",
            "tools": [
                {
                    "name": "resume.read",
                    "version": "1.0.0",
                    "owner": "resume-intelligence-team",
                    "description": "Read a resume owned by the current user.",
                    "risk_level": "medium",
                    "read_only": True,
                    "requires_approval": False,
                    "allowed_agents": ["resume-analyst"],
                    "required_arguments": ["resume_id", "audience"],
                    "output_fields": ["resume_text"],
                }
            ],
        }

    def test_active_mcp_registry_accepts_authorized_read_tool(self) -> None:
        errors = mcp_validator.validate_registry(self.active_registry(), known_agents={"resume-analyst"})

        self.assertEqual(errors, [])

    def test_mcp_registry_rejects_write_tool_without_approval_and_unknown_agent(self) -> None:
        data = self.active_registry()
        tool = data["tools"][0]
        tool["read_only"] = False
        tool["allowed_agents"] = ["unknown-agent"]

        errors = mcp_validator.validate_registry(data, known_agents={"resume-analyst"})

        self.assertTrue(any("write-capable tools must require approval" in error for error in errors))
        self.assertTrue(any("references unknown agent: unknown-agent" in error for error in errors))

    def test_mcp_registry_rejects_duplicate_invalid_tool_contracts(self) -> None:
        data = self.active_registry()
        first = data["tools"][0]
        first["version"] = "v1"
        first["output_fields"] = []
        duplicate = copy.deepcopy(first)
        data["tools"].append(duplicate)

        errors = mcp_validator.validate_registry(data, known_agents={"resume-analyst"})

        self.assertTrue(any("version must be SemVer" in error for error in errors))
        self.assertTrue(any("output_fields must not be empty" in error for error in errors))
        self.assertTrue(any("duplicate tool name: resume.read" in error for error in errors))

    def test_planned_mcp_registry_must_not_publish_tools(self) -> None:
        data = self.active_registry()
        data["status"] = "planned"

        errors = mcp_validator.validate_registry(data, known_agents={"resume-analyst"})

        self.assertIn("planned registry must not contain active tool definitions", errors)


class SkillRegistryValidationTest(unittest.TestCase):
    def test_active_skill_requires_real_skill_file_and_typed_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_path = root / "skills" / "truthful-resume-rewrite"
            skill_path.mkdir(parents=True)
            (skill_path / "SKILL.md").write_text("# Truthful resume rewrite\n", encoding="utf-8")
            data = {
                "schema_version": "1.0",
                "status": "active",
                "phase": "phase-1-skills",
                "owner": "agent-platform-team",
                "skills": [
                    {
                        "id": "truthful-resume-rewrite",
                        "version": "1.0.0",
                        "owner": "resume-intelligence-team",
                        "path": "skills/truthful-resume-rewrite",
                        "description": "Rewrite only from verified evidence.",
                        "inputs": [
                            {
                                "name": "evidence_bundle",
                                "type": "EvidenceBundle",
                                "required": True,
                                "description": "Verified source facts.",
                            }
                        ],
                        "outputs": [
                            {
                                "name": "resume_patch",
                                "type": "ResumePatch",
                                "description": "Evidence-linked proposed edits.",
                            }
                        ],
                        "risk_level": "high",
                    }
                ],
            }

            errors = skill_validator.validate_registry(data, root=root)

        self.assertEqual(errors, [])

    def test_skill_registry_rejects_path_traversal_and_untyped_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {
                "schema_version": "1.0",
                "status": "active",
                "phase": "phase-1-skills",
                "owner": "agent-platform-team",
                "skills": [
                    {
                        "id": "resume-skill",
                        "version": "1",
                        "owner": "team",
                        "path": "../outside",
                        "description": "Skill",
                        "inputs": [{"name": "Evidence Bundle", "type": "", "required": "yes"}],
                        "outputs": [],
                        "risk_level": "critical",
                    }
                ],
            }

            errors = skill_validator.validate_registry(data, root=root)

        self.assertTrue(any("version must be SemVer" in error for error in errors))
        self.assertTrue(any("path must stay within" in error for error in errors))
        self.assertTrue(any("inputs[0].required must be a boolean" in error for error in errors))
        self.assertTrue(any("outputs must contain at least one field" in error for error in errors))


class QualityGateConsoleTest(unittest.TestCase):
    def test_console_safe_text_replaces_unencodable_characters(self) -> None:
        rendered = quality_gate._console_safe_text("failure: \ufffd", encoding="gbk")

        self.assertEqual(rendered, "failure: ?")


class QualityEvidenceTest(unittest.TestCase):
    def test_git_evidence_hash_includes_untracked_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            untracked = root / "new.txt"
            untracked.write_text("first", encoding="utf-8")

            def fake_run_git(*args: str, text: bool = False) -> subprocess.CompletedProcess[bytes | str]:
                if args == ("rev-parse", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "abc123\n", "")
                if args[0] == "status":
                    return subprocess.CompletedProcess(["git"], 0, b"?? new.txt\0", b"")
                return subprocess.CompletedProcess(["git"], 0, b"", b"")

            with patch.object(quality_gate, "ROOT", root), patch.object(quality_gate, "_run_git", fake_run_git):
                before = quality_gate._git_evidence()
                untracked.write_text("second", encoding="utf-8")
                after = quality_gate._git_evidence()

        self.assertTrue(before["dirty"])
        self.assertEqual(before["untracked_file_count"], 1)
        self.assertNotEqual(before["worktree_sha256"], after["worktree_sha256"])

    def test_secret_scan_distinguishes_scanned_and_skipped_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text_file = root / "config.txt"
            text_file.write_text("token=sk-example-not-a-secret\n", encoding="utf-8")
            binary_file = root / "binary.bin"
            binary_file.write_bytes(b"\xff\xfe\x00")

            with patch.object(secret_scan, "ROOT", root):
                text_result = secret_scan._scan(text_file)
                binary_result = secret_scan._scan(binary_file)

        self.assertEqual(text_result, [])
        self.assertIsNone(binary_result)


class DeploymentContractValidatorTest(unittest.TestCase):
    @staticmethod
    def _write_fixture(
        root: Path,
        *,
        docker_python: str = "3.12",
        shadow_enabled: str = "false",
        run_store_backend: str = "postgresql",
        database_url: str = "postgresql+asyncpg://user:password@postgres/app",
    ) -> None:
        backend = root / "backend"
        backend.mkdir()
        (backend / "pyproject.toml").write_text('[tool.mypy]\npython_version = "3.12"\n', encoding="utf-8")
        (backend / "Dockerfile").write_text(f"FROM python:{docker_python}-slim\n", encoding="utf-8")
        (backend / ".env.production.example").write_text(
            f"DATABASE_URL={database_url}\n"
            f"AGENT_SHADOW_API_ENABLED={shadow_enabled}\n"
            f"AGENT_RUN_STORE_BACKEND={run_store_backend}\n",
            encoding="utf-8",
        )
        (root / "docker-compose.yml").write_text(
            "postgres:16\n"
            "  environment:\n"
            '    AGENT_SHADOW_API_ENABLED: "false"\n'
            "    AGENT_RUN_STORE_BACKEND: postgresql\n"
            "    DATABASE_URL: postgresql+asyncpg://user:password@postgres/app\n"
            "  migrate:\n  backend:\n  worker:\n  frontend:\n",
            encoding="utf-8",
        )
        (root / ".gitignore").write_text("/artifacts/\n", encoding="utf-8")

    def test_matching_runtime_and_fail_closed_shadow_config_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_fixture(root)

            self.assertEqual(deployment_validator.validate_deployment_contracts(root=root), [])

    def test_runtime_drift_and_enabled_shadow_config_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_fixture(
                root,
                docker_python="3.11",
                shadow_enabled="true",
                run_store_backend="memory",
                database_url="sqlite+aiosqlite:///./app.db",
            )

            errors = deployment_validator.validate_deployment_contracts(root=root)

            self.assertTrue(any("does not match pyproject runtime" in error for error in errors))
            self.assertTrue(any("AGENT_SHADOW_API_ENABLED=false" in error for error in errors))
            self.assertTrue(any("AGENT_RUN_STORE_BACKEND=postgresql" in error for error in errors))
            self.assertTrue(any("postgresql+asyncpg DATABASE_URL" in error for error in errors))


class DocumentationValidatorTest(unittest.TestCase):
    def test_local_link_and_clean_markdown_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "docs"
            docs.mkdir()
            target = docs / "TARGET.md"
            target.write_text("# Target\n", encoding="utf-8")
            source = docs / "SOURCE.md"
            source.write_text("# Source\n\n[Target](./TARGET.md)\n", encoding="utf-8")

            self.assertEqual(documentation_validator.validate_markdown_file(source, root=root), [])

    def test_missing_and_escaping_links_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "docs"
            docs.mkdir()
            source = docs / "SOURCE.md"
            source.write_text("[Missing](./missing.md)\n[Outside](../../outside.md)\n", encoding="utf-8")

            errors = documentation_validator.validate_markdown_file(source, root=root)

            self.assertTrue(any("missing local link target" in error for error in errors))
            self.assertTrue(any("link escapes repository" in error for error in errors))

    def test_trailing_whitespace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "README.md"
            source.write_text("# Title  \n", encoding="utf-8")

            errors = documentation_validator.validate_markdown_file(source, root=root)

            self.assertEqual(errors, ["README.md:1: trailing whitespace"])


if __name__ == "__main__":
    unittest.main()
