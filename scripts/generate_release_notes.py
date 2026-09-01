import os
import re
import subprocess
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent

# Commits that say nothing the tag or the diff doesn't already say.
TRIVIAL_COMMIT = re.compile(
    r"format|lint|style|prettier|eslint|black|isort|flake8|mypy|type.?check|bump.{0,10}version",
    re.IGNORECASE,
)
CONVENTIONAL_COMMIT = re.compile(r"^(\w+)(?:\(([^)]+)\))?!?:\s*(.+)$")

SECTION_FOR_TYPE = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "refactor": "Improvements",
    "perf": "Improvements",
}
SECTION_ORDER = ["Features", "Bug Fixes", "Improvements", "Other Changes"]


def get_merge_commit_details(commit_hash):
    """Extract commits from a merge commit to get the actual changes."""
    result = subprocess.run(
        ["git", "log", "--oneline", f"{commit_hash}^1..{commit_hash}^2"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    commits = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split(" ", 1)
        if len(parts) > 1:
            commits.append(parts[1].strip())
    return commits


def get_commits_between_releases(last_release, current_tag):
    """Collect commit subjects between two tags, expanding merge commits into their contents."""
    range_spec = f"{last_release}..{current_tag}" if last_release else current_tag
    print(f"Getting commits for release notes: {range_spec}")

    result_merges = subprocess.run(
        ["git", "log", range_spec, "--pretty=format:%H|%s", "--merges"],
        capture_output=True,
        text=True,
    )
    merge_commits = result_merges.stdout.strip().split("\n") if result_merges.stdout.strip() else []

    result_commits = subprocess.run(
        ["git", "log", range_spec, "--pretty=format:%s", "--no-merges"],
        capture_output=True,
        text=True,
    )
    regular_commits = result_commits.stdout.strip().split("\n") if result_commits.stdout.strip() else []

    subjects = []
    for commit_line in merge_commits:
        if not commit_line.strip():
            continue
        commit_hash, commit_message = commit_line.split("|", 1)
        if re.search(r"dev.*staging|staging.*main", commit_message, re.IGNORECASE) or re.match(
            r"^Merge branch", commit_message
        ):
            # The merge subject itself is noise; the commits it carried are the changes.
            subjects.extend(get_merge_commit_details(commit_hash))

    subjects.extend(commit.strip() for commit in regular_commits if commit.strip())

    seen = set()
    filtered = []
    for subject in subjects:
        if TRIVIAL_COMMIT.search(subject) or subject in seen:
            continue
        seen.add(subject)
        filtered.append(subject)
    return filtered


def format_release_notes(subjects):
    sections = {title: [] for title in SECTION_ORDER}
    for subject in subjects:
        match = CONVENTIONAL_COMMIT.match(subject)
        if match:
            commit_type, scope, description = match.groups()
            title = SECTION_FOR_TYPE.get(commit_type.lower(), "Other Changes")
            bullet = f"- **{scope}**: {description}" if scope else f"- {description}"
        else:
            title = "Other Changes"
            bullet = f"- {subject}"
        sections[title].append(bullet)

    parts = []
    for title in SECTION_ORDER:
        if sections[title]:
            parts.append(f"## {title}")
            parts.extend(sections[title])
            parts.append("")
    return "\n".join(parts).strip()


def get_changelog_section(version: str) -> str | None:
    changelog_path = project_root / "CHANGELOG.md"
    if not changelog_path.exists():
        return None
    header = re.compile(rf"^##\s+\[?{re.escape(version)}\]?(\s|$)")
    section = []
    in_section = False
    for line in changelog_path.read_text().splitlines():
        if in_section:
            if line.startswith("## "):
                break
            section.append(line)
        elif header.match(line):
            in_section = True
    text = "\n".join(section).strip()
    return text or None


def get_version_from_version_py() -> str:
    version_path = project_root / "app" / "core" / "version.py"
    match = re.search(r'__version__\s*=\s*"([^"]*)"', version_path.read_text())
    if match:
        return match.group(1)
    print("Warning: could not read version from version.py")
    return "0.0.0"


def is_prerelease(version: str) -> bool:
    return any(marker in version.lower() for marker in ("alpha", "beta", "rc", "pre", "dev"))


def get_all_tags() -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--sort=-version:refname"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [tag.strip() for tag in result.stdout.strip().split("\n") if tag.strip()]


def get_previous_release_tag(current_version: str) -> str | None:
    """Previous tag to diff against: pre-releases compare to any tag, stable releases skip pre-releases."""
    all_tags = get_all_tags()
    if not all_tags:
        return None

    try:
        current_index = all_tags.index(current_version)
    except ValueError:
        current_index = 0

    current_is_prerelease = is_prerelease(current_version)
    for i in range(current_index + 1, len(all_tags)):
        tag = all_tags[i]
        if current_is_prerelease or not is_prerelease(tag):
            return tag
    return None


def write_to_github_output(name, value):
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"{name}<<EOF\n{value}\nEOF\n")


def main():
    current_tag = os.environ.get("CURRENT_TAG")
    if not current_tag:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            current_tag = result.stdout.strip()

    if not current_tag:
        current_tag = get_version_from_version_py()
        print(f"Warning: no tag found, using version from version.py: {current_tag}")

    print(f"Current Tag/Version: {current_tag}")

    release_notes = get_changelog_section(current_tag)
    if release_notes:
        print("Using release notes from CHANGELOG.md")
    else:
        last_release_tag = get_previous_release_tag(current_tag)
        print(f"No CHANGELOG.md entry for {current_tag}, falling back to commits since {last_release_tag}")
        subjects = get_commits_between_releases(last_release_tag, current_tag)
        release_notes = format_release_notes(subjects) or "No significant changes to describe."
    print(f"Release Notes:\n{release_notes}")

    write_to_github_output("release_notes", release_notes)


if __name__ == "__main__":
    main()
