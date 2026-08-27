from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

from scripts.youtube_enhance.workflow_state import ArtifactRecord


def run_git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def create_seeded_repository(parent: Path) -> tuple[Path, Path]:
    primary = parent / "primary"
    linked = parent / "linked"
    primary.mkdir(parents=True)
    run_git(primary, "init", "-b", "main")
    run_git(primary, "config", "user.name", "Workflow Tests")
    run_git(primary, "config", "user.email", "workflow-tests@example.invalid")
    skill = primary / ".agents" / "skills" / "enhancing-lecture-audio" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Installed test skill\n", encoding="utf-8")
    run_git(primary, "add", ".agents/skills/enhancing-lecture-audio/SKILL.md")
    run_git(primary, "commit", "-m", "seed repository")
    run_git(primary, "worktree", "add", "-b", "linked-tests", str(linked))
    return primary, linked


def create_directory_reparse(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise

    completed = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise OSError(completed.stderr or completed.stdout or "could not create directory junction")


def remove_directory_reparse(link: Path) -> None:
    if not os.path.lexists(link):
        return
    if os.name == "nt":
        os.rmdir(link)
    else:
        link.unlink()


def artifact_record(path: Path, relative_path: str) -> ArtifactRecord:
    status = path.stat(follow_symlinks=False)
    return ArtifactRecord(
        relative_path=relative_path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=status.st_size,
        file_id=(status.st_dev, status.st_ino),
        media=None,
    )
