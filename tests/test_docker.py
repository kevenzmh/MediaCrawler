# -*- coding: utf-8 -*-
"""Unit tests for Docker deployment infrastructure."""

import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


class TestDockerfileExists:
    def test_dockerfile_exists(self):
        assert (PROJECT_ROOT / "Dockerfile").exists()

    def test_dockerignore_exists(self):
        assert (PROJECT_ROOT / ".dockerignore").exists()

    def test_docker_compose_exists(self):
        assert (PROJECT_ROOT / "docker-compose.yml").exists()

    def test_docker_compose_override_example_exists(self):
        assert (PROJECT_ROOT / "docker-compose.override.yml.example").exists()

    def test_docker_guide_exists(self):
        assert (PROJECT_ROOT / "docs" / "docker_guide.md").exists()


class TestDockerfileContent:
    @pytest.fixture
    def dockerfile_content(self):
        return (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    def test_base_image(self, dockerfile_content):
        assert "python:3.11-slim" in dockerfile_content

    def test_nodejs_installed(self, dockerfile_content):
        assert "nodejs" in dockerfile_content.lower()

    def test_playwright_installed(self, dockerfile_content):
        assert "playwright" in dockerfile_content.lower()

    def test_non_root_user(self, dockerfile_content):
        assert "crawler" in dockerfile_content
        assert "USER" in dockerfile_content

    def test_healthcheck(self, dockerfile_content):
        assert "HEALTHCHECK" in dockerfile_content

    def test_volume(self, dockerfile_content):
        assert "VOLUME" in dockerfile_content

    def test_entrypoint(self, dockerfile_content):
        assert "ENTRYPOINT" in dockerfile_content or "CMD" in dockerfile_content

    def test_uv_used(self, dockerfile_content):
        assert "uv" in dockerfile_content


class TestDockerComposeContent:
    @pytest.fixture
    def compose_content(self):
        return (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    def test_mediacrawler_service(self, compose_content):
        assert "mediacrawler" in compose_content

    def test_build_reference(self, compose_content):
        assert "build:" in compose_content or "image:" in compose_content

    def test_volume_mounts(self, compose_content):
        assert "volumes:" in compose_content

    def test_environment_variables(self, compose_content):
        assert "environment:" in compose_content or "env_file:" in compose_content

    def test_optional_db_service(self, compose_content):
        assert "mysql" in compose_content.lower() or "db:" in compose_content

    def test_profiles(self, compose_content):
        assert "profile" in compose_content.lower()


class TestDockerignore:
    @pytest.fixture
    def ignore_content(self):
        return (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    def test_excludes_pycache(self, ignore_content):
        assert "__pycache__" in ignore_content

    def test_excludes_git(self, ignore_content):
        assert ".git" in ignore_content

    def test_excludes_data(self, ignore_content):
        assert "data" in ignore_content

    def test_excludes_browser_data(self, ignore_content):
        assert "browser_data" in ignore_content or "user_data" in ignore_content

    def test_excludes_ide_files(self, ignore_content):
        assert ".vscode" in ignore_content or ".idea" in ignore_content
