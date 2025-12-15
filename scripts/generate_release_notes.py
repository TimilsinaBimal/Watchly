import os
import re
import subprocess
import sys
from pathlib import Path
from traceback import print_exc

from openai import OpenAI
from pydantic import BaseModel

# Add project root to path to import version
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
oai_client = OpenAI(api_key=OPENAI_API_KEY)


def get_current_branch():
    result = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip()


def get_commit_hash():
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip()


def get_last_release_tag():
    result = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_merge_commit_details(commit_hash):
    """Extract commits from a merge commit to get the actual changes."""
    try:
        # Get commits from the second parent (the branch being merged)
        result = subprocess.run(
            ["git", "log", "--oneline", f"{commit_hash}^1..{commit_hash}^2"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            commits = result.stdout.strip().split("\n")
            # Clean up the commit messages (remove the hash prefix)
            cleaned_commits = []
            for commit in commits:
                if commit.strip():
                    # Remove the commit hash (first 7 characters + space)
                    parts = commit.split(" ", 1)
                    if len(parts) > 1:
                        cleaned_commits.append(parts[1])
            return cleaned_commits
    except Exception as e:
        print(f"Error extracting commits from merge {commit_hash}: {e}")
    return []


def get_commits_between_releases(last_release, current_tag):
    """Get commits between two tags for release notes generation."""
    if last_release:
        range_spec = f"{last_release}..{current_tag}"
    else:
        # If no previous release, get all commits up to current tag
        range_spec = current_tag
    print(f"Getting commits for release notes: {range_spec}")

    # Get merge commits with their hashes (these are the important ones in our flow)
    result_merges = subprocess.run(
        ["git", "log", range_spec, "--pretty=format:%H|%s", "--merges"],
        capture_output=True,
        text=True,
    )
    merge_commits = result_merges.stdout.strip().split("\n") if result_merges.stdout.strip() else []

    # Get regular commits (excluding merges)
    result_commits = subprocess.run(
        ["git", "log", range_spec, "--pretty=format:%s", "--no-merges"],
        capture_output=True,
        text=True,
    )
    regular_commits = result_commits.stdout.strip().split("\n") if result_commits.stdout.strip() else []

    # Filter and combine commits
    filtered_commits = []

    # Process merge commits and extract their details
    for commit_line in merge_commits:
        if not commit_line.strip():
            continue

        commit_hash, commit_message = commit_line.split("|", 1)

        # Include merges from dev to staging and staging to main
        if re.search(r"dev.*staging|staging.*main", commit_message, re.IGNORECASE) or re.match(
            r"^Merge branch", commit_message
        ):
            # For important merge commits, extract the actual commits that were merged
            merge_details = get_merge_commit_details(commit_hash)
            if merge_details:
                # Add the merge commit itself
                filtered_commits.append(commit_message.strip())
                # Add the individual commits from the merge (but filter them)
                for detail_commit in merge_details:
                    if detail_commit.strip() and not re.search(
                        r"(format|lint|style|prettier|eslint|black|isort|flake8|mypy|type.?check)",
                        detail_commit,
                        re.IGNORECASE,
                    ):
                        filtered_commits.append(f"  {detail_commit.strip()}")
            else:
                filtered_commits.append(commit_message.strip())

    # Include regular commits but exclude trivial ones
    for commit in regular_commits:
        if commit.strip():
            # Exclude trivial commits like formatting, linting, etc.
            if not re.search(
                r"(format|lint|style|prettier|eslint|black|isort|flake8|mypy|type.?check)",
                commit,
                re.IGNORECASE,
            ):
                filtered_commits.append(commit.strip())

    return "\n".join(filtered_commits)


class ReleaseNotes(BaseModel):
    release_notes: str
    version_name: str


def get_version_from_version_py() -> str:
    """Read version from app/core/version.py using regex (avoids import dependencies)."""
    try:
        version_path = project_root / "app" / "core" / "version.py"
        if version_path.exists():
            content = version_path.read_text()
            match = re.search(r'__version__\s*=\s*"([^"]*)"', content)
            if match:
                version = match.group(1)
                print(f"Read version from version.py: {version}")
                return version
        print("Warning: version.py not found")
        return "0.0.0"
    except Exception as e:
        print(f"Error reading version.py: {e}")
        return "0.0.0"


def is_prerelease(version: str) -> bool:
    """Check if version is a pre-release (contains alpha, beta, rc, etc.)."""
    prerelease_patterns = [r"alpha", r"beta", r"rc", r"pre", r"dev"]
    version_lower = version.lower()
    return any(re.search(pattern, version_lower) for pattern in prerelease_patterns)


def get_all_tags() -> list[str]:
    """Get all tags sorted by version."""
    try:
        result = subprocess.run(
            ["git", "tag", "--sort=-version:refname"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            tags = [tag.strip() for tag in result.stdout.strip().split("\n") if tag.strip()]
            return tags
        return []
    except Exception as e:
        print(f"Error getting tags: {e}")
        return []


def get_previous_release_tag(current_version: str) -> str | None:
    """Get the appropriate previous release tag based on pre-release logic."""
    all_tags = get_all_tags()
    current_is_prerelease = is_prerelease(current_version)

    if not all_tags:
        return None

    # Find current tag in the list
    try:
        current_index = all_tags.index(current_version)
    except ValueError:
        # Current version not in tags, use the first tag as reference
        current_index = 0

    # If current is a pre-release, find previous pre-release or stable
    # If current is stable, find previous stable (skip pre-releases)
    for i in range(current_index + 1, len(all_tags)):
        tag = all_tags[i]
        tag_is_prerelease = is_prerelease(tag)

        if current_is_prerelease:
            # For pre-releases, include any previous release (stable or pre-release)
            return tag
        else:
            # For stable releases, only include previous stable releases
            if not tag_is_prerelease:
                return tag

    return None


def generate_release_notes(commits, last_release_tag):
    prompt = (
        "Generate release notes for the given commits. Focus on user-facing changes and important technical"
        " improvements that stakeholders care about Organize changes into clear sections such as: Summary,"
        " Features, Bug Fixes, Improvements, etc. with markdown formatting. Include PR requests with (#123) at"
        " the end of each change. Include refactor commits only if they contain meaningful architectural"
        " changes. Exclude trivial changes like formatting, linting, merge commits, or dependency updates"
        " unless they're significant. Format with proper markdown. Do not include commit hashes. When"
        " generating release notes, do not just write commit messages. Describe them. Try to make them like"
        " release change.Do not output anything other than the release notes. Keep it to a reasonable length"
        " that helps developers and engineers understand the changes. This is directly attached to GitHub"
        " release notes, so please do not include anything other than required.\n\nAdditionally, suggest a"
        " unique version name inspired by something beautiful and unique to Nepal (such as a place, temple,"
        " bird, animal, hill, or mountain). The version name should be relevant to the spirit of the changes if"
        " possible. Return your response as a JSON object with two fields: 'release_notes' (markdown) and"
        " 'version_name' (string). Only output valid JSON."
    )
    try:
        response = oai_client.responses.parse(
            model="gpt-5-mini",
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"## Last release tag: {last_release_tag}\n ## Commits: {commits}"},
            ],
            text_format=ReleaseNotes,
        )
        parsed_output = response.output_parsed
        release_notes = parsed_output.release_notes
        version_name = parsed_output.version_name
        return release_notes, version_name
    except Exception as e:
        print(f"Error generating release notes with LLM: {e}")
        print_exc()

    try:
        commit_list = commits.split("\n")
        if not commit_list or all(not commit.strip() for commit in commit_list):
            return "No significant changes to describe."

        formatted_notes = []
        features = []
        fixes = []
        improvements = []
        technical = []
        other = []

        for commit in commit_list:
            if not commit.strip():
                continue

            commit_lower = commit.lower()
            if any(word in commit_lower for word in ["feat", "feature", "add"]):
                features.append(commit.strip())
            elif any(word in commit_lower for word in ["fix", "bug", "issue"]):
                fixes.append(commit.strip())
            elif any(word in commit_lower for word in ["improve", "enhance", "update", "refactor"]):
                improvements.append(commit.strip())
            elif any(word in commit_lower for word in ["tech", "config", "deps", "ci", "test"]):
                technical.append(commit.strip())
            else:
                other.append(commit.strip())

        if features:
            formatted_notes.append("## Features")
            formatted_notes.extend(f"* {feat}" for feat in features)

        if fixes:
            formatted_notes.append("\n## Bug Fixes")
            formatted_notes.extend(f"* {fix}" for fix in fixes)

        if improvements:
            formatted_notes.append("\n## Improvements")
            formatted_notes.extend(f"* {imp}" for imp in improvements)

        if technical:
            formatted_notes.append("\n## Technical Changes")
            formatted_notes.extend(f"* {tech}" for tech in technical)

        if other:
            formatted_notes.append("\n## Other Changes")
            formatted_notes.extend(f"* {oth}" for oth in other)

        return "\n".join(formatted_notes), ""
    except Exception as e:
        print(f"Error generating formatted PR description: {e}")
        return "", ""


def write_to_github_output(name, value):
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"{name}<<EOF\n{value}\nEOF\n")


def main():
    # Get current tag from environment (set by GitHub Actions) or from git
    current_tag = os.environ.get("CURRENT_TAG")
    if not current_tag:
        # Try to get from git ref
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--exact-match", "HEAD"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                current_tag = result.stdout.strip()
        except Exception:
            pass

    if not current_tag:
        # Fallback: read from version.py
        current_tag = get_version_from_version_py()
        print(f"Warning: No tag found, using version from version.py: {current_tag}")

    print(f"Current Tag/Version: {current_tag}")

    # Get the appropriate previous release based on pre-release logic
    last_release_tag = get_previous_release_tag(current_tag)
    print(f"Previous Release Tag: {last_release_tag}")

    commits = get_commits_between_releases(last_release_tag, current_tag)

    # Use current tag as version
    version = current_tag

    if commits:
        print(f"Commits for release notes: {commits}")

        # Generate release notes (without version, we read it from version.py)
        release_notes, version_name = generate_release_notes(commits, last_release_tag)
        print(f"Release Notes: {release_notes}")
        print(f"Version Name: {version_name}")
        print(f"Version (from version.py): {version}")

        write_to_github_output("release_notes", release_notes)
        write_to_github_output("version_name", version_name)
        write_to_github_output("version", version)
    else:
        # No commits, but still use version from version.py
        print(f"No commits found, using version from version.py: {version}")
        write_to_github_output("release_notes", "No significant changes to describe.")
        write_to_github_output("version_name", "Pashupatinath")
        write_to_github_output("version", version)


if __name__ == "__main__":
    main()
