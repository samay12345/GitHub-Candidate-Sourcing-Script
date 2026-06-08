#!/usr/bin/env python3
"""GitHub candidate sourcing script.

Searches public GitHub repositories for a role + tech stack, ranks candidate
contributors, and outputs a CSV/Google Sheet-friendly result set.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from dotenv import load_dotenv

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:  # pragma: no cover - optional dependency
    gspread = None
    Credentials = None

load_dotenv()

GITHUB_API = "https://api.github.com"
DEFAULT_OUTPUT = Path("output/candidates.csv")


class GitHubError(RuntimeError):
    """Raised when the GitHub API request fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find relevant GitHub candidates")
    parser.add_argument("--role", required=True, help="Role to target, e.g. founding engineer")
    parser.add_argument(
        "--experience-years",
        type=int,
        default=None,
        help="Minimum years of experience required, e.g. 3",
    )
    parser.add_argument(
        "--tech-stack",
        required=True,
        help="Comma-separated tech stack, e.g. rust,python,cpp",
    )
    parser.add_argument("--limit", type=int, default=10, help="Number of candidates to return")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="CSV file path for results",
    )
    parser.add_argument(
        "--sheet-name",
        default=os.getenv("GOOGLE_SHEETS_SHEET_NAME"),
        help="Optional Google Sheet name to append results to",
    )
    parser.add_argument(
        "--credentials",
        default=os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE"),
        help="Path to Google service account JSON credentials",
    )
    return parser.parse_args()


def make_request(url: str, params: Dict[str, object] | None = None) -> Dict | List:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "candidate-sourcing-script",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, params=params, timeout=60)
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise GitHubError("GitHub API rate limit exceeded. Set GITHUB_TOKEN in .env for a higher limit.")
    if response.status_code >= 400:
        raise GitHubError(f"GitHub API request failed: {response.status_code} {response.text}")
    return response.json()


def build_query(role: str, tech_stack: List[str], experience_years: int | None = None) -> str:
    tokens = [role]
    if experience_years is not None:
        tokens.append(f"{experience_years}+ years experience")
    tokens.extend(tech_stack)
    tokens = [t.strip() for t in tokens if t.strip()]
    tokens = [re.sub(r"\s+", " ", t) for t in tokens]
    return " ".join(tokens)


def build_query_variants(role: str, tech_stack: List[str], experience_years: int | None = None) -> List[str]:
    clean_role = re.sub(r"\s+", " ", role).strip()
    experience_text = f"{experience_years}+ years experience" if experience_years is not None else None
    clean_stack = [re.sub(r"\s+", " ", item).strip() for item in tech_stack if item.strip()]

    language_terms = [f"language:{item}" for item in clean_stack if item]
    base_terms = [clean_role]
    if experience_text:
        base_terms.append(experience_text)
    base_terms.extend(clean_stack)
    base_query = " ".join(base_terms)

    variants = [
        base_query,
        f'"{clean_role}" "{clean_stack[0]}"' if clean_stack else clean_role,
        f'"{clean_role}" developer ' + " ".join(clean_stack) if clean_stack else clean_role,
        f'"{clean_role}" open source ' + " ".join(clean_stack) if clean_stack else clean_role,
    ]

    for query in list(variants):
        if language_terms:
            variants.append(f"{query} {' '.join(language_terms)}")
        variants.append(f"{query} in:name,description")

    seen = set()
    unique_queries = []
    for item in variants:
        normalized = re.sub(r"\s+", " ", item).strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_queries.append(item)
    return unique_queries


def search_repositories(query: str, per_page: int = 10, page: int = 1) -> List[Dict]:
    """Search repositories using the public GitHub search API."""
    params = {
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": per_page,
        "page": page,
    }
    data = make_request(f"{GITHUB_API}/search/repositories", params)
    return data.get("items", []) if isinstance(data, dict) else []


def fetch_user(login: str) -> Dict:
    return make_request(f"{GITHUB_API}/users/{login}")


def fetch_user_repos(login: str, per_page: int = 3) -> List[Dict]:
    params = {"sort": "updated", "direction": "desc", "per_page": per_page}
    return make_request(f"{GITHUB_API}/users/{login}/repos", params)


def summarize_candidate(user: Dict, repos: List[Dict]) -> str:
    bio = (user.get("bio") or "").strip()
    repo_names = [repo.get("name", "") for repo in repos[:3] if repo.get("name")]
    languages = sorted({repo.get("language") for repo in repos if repo.get("language")})
    language_text = ", ".join(languages[:4]) if languages else "public repositories"
    repo_text = ", ".join(repo_names[:3]) if repo_names else "recent public work"
    if bio:
        return f"{user.get('login', 'This candidate')} has public work in {language_text} with notable repositories like {repo_text}; bio: {bio}"
    return f"{user.get('login', 'This candidate')} has public work in {language_text} and relevant repositories such as {repo_text}."


def is_us_location(location: str) -> bool:
    text = (location or "").strip().lower()
    if not text:
        return False
    us_markers = [
        "united states", "usa", "us", "u.s.", "u.s.a.", "america",
        "california", "new york", "texas", "florida", "illinois", "pennsylvania",
        "ohio", "georgia", "north carolina", "new jersey", "virginia", "washington",
        "massachusetts", "arizona", "massachusetts", "michigan", "indiana", "tennessee",
        "missouri", "maryland", "wisconsin", "colorado", "minnesota", "south carolina",
        "alabama", "louisiana", "kentucky", "oregon", "oklahoma", "connecticut",
        "iowa", "mississippi", "arkansas", " kansas", "utah", "nevada", "new mexico",
        "nebraska", "idaho", "hawaii", "maine", "new hampshire", "rhode island",
        "montana", "delaware", "south dakota", "north dakota", "alaska", "vermont",
        "wyoming", "district of columbia", "dc",
    ]
    return any(marker in text for marker in us_markers)


def score_candidate(user: Dict, repos: List[Dict], matching_repo_count: int, tech_stack: List[str]) -> int:
    score = 0
    score += min(matching_repo_count * 8, 40)
    score += min(user.get("followers", 0), 20)
    score += min(user.get("public_repos", 0), 10)

    tech_set = {item.lower() for item in tech_stack}
    for repo in repos[:5]:
        language = (repo.get("language") or "").lower()
        if language in tech_set:
            score += 6
        if repo.get("stargazers_count", 0):
            score += min(repo["stargazers_count"] // 10, 10)
    return score


def build_candidates(role: str, tech_stack: List[str], limit: int = 10, experience_years: int | None = None) -> List[Dict]:
    queries = build_query_variants(role, tech_stack, experience_years)
    repos = []
    seen_repo_ids = set()

    for query in queries[:4]:
        for page in range(1, 3):
            items = search_repositories(query, per_page=10, page=page)
            for repo in items:
                repo_id = repo.get("id")
                if repo_id and repo_id not in seen_repo_ids:
                    seen_repo_ids.add(repo_id)
                    repos.append(repo)

    owner_map: Dict[str, List[Dict]] = defaultdict(list)
    for repo in repos:
        owner = repo.get("owner", {}).get("login")
        if owner:
            owner_map[owner].append(repo)

    candidates = []
    for login, repo_items in owner_map.items():
        try:
            user = fetch_user(login)
            user_repos = fetch_user_repos(login, per_page=3)
        except GitHubError:
            continue

        if not is_us_location(user.get("location")):
            continue

        matching_repo_count = len(repo_items)
        repos_to_use = [repo for repo in user_repos if repo.get("name")]
        score = score_candidate(user, repos_to_use, matching_repo_count, tech_stack)
        candidates.append({
            "username": user.get("login"),
            "public_email": user.get("email") or "",
            "most_relevant_repo": repo_items[0].get("html_url") if repo_items else "",
            "relevance_summary": summarize_candidate(user, repos_to_use),
            "location": user.get("location") or "",
            "score": score,
            "followers": user.get("followers", 0),
            "public_repos": user.get("public_repos", 0),
            "bio": user.get("bio") or "",
        })

    candidates.sort(key=lambda item: (-item["score"], item["username"]))
    return candidates[:limit]


def write_csv(candidates: List[Dict], output_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "GitHub username",
        "Public email if available",
        "Link to their most relevant repository",
        "One line summary of why they are relevant",
        "Location if listed",
        "Score",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in candidates:
            writer.writerow({
                "GitHub username": item["username"],
                "Public email if available": item["public_email"],
                "Link to their most relevant repository": item["most_relevant_repo"],
                "One line summary of why they are relevant": item["relevance_summary"],
                "Location if listed": item["location"],
                "Score": item["score"],
            })
    return path


def write_to_google_sheet(candidates: List[Dict], sheet_name: str, credentials_file: str) -> None:
    if not gspread or not Credentials:
        raise RuntimeError("gspread / google-auth is not installed. Install requirements.txt first.")
    if not sheet_name:
        raise RuntimeError("A Google Sheet name is required when writing to Sheets.")
    if not credentials_file or not os.path.exists(credentials_file):
        raise RuntimeError("A valid Google service account JSON file is required.")

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_file(credentials_file, scopes=scopes)
    client = gspread.authorize(credentials)

    try:
        spreadsheet = client.open(sheet_name)
    except gspread.SpreadsheetNotFound:
        spreadsheet = client.create(sheet_name)

    worksheet = spreadsheet.sheet1
    existing_values = worksheet.get_all_values()
    if not existing_values:
        worksheet.append_row([
            "GitHub username",
            "Public email if available",
            "Link to their most relevant repository",
            "One line summary of why they are relevant",
            "Location if listed",
            "Score",
        ])

    for item in candidates:
        worksheet.append_row([
            item["username"],
            item["public_email"],
            item["most_relevant_repo"],
            item["relevance_summary"],
            item["location"],
            item["score"],
        ])

    print(f"Google Sheet updated: {spreadsheet.url}")


def main() -> None:
    args = parse_args()
    tech_stack = [item.strip() for item in args.tech_stack.split(",") if item.strip()]

    try:
        candidates = build_candidates(
            args.role,
            tech_stack,
            limit=args.limit,
            experience_years=args.experience_years,
        )
        if not candidates:
            print("No candidates found. Try a broader role/stack combination.")
            return

        if args.sheet_name and args.credentials:
            try:
                write_to_google_sheet(candidates, args.sheet_name, args.credentials)
            except Exception as exc:
                print(f"Google Sheets export failed: {exc}", file=sys.stderr)

        output_path = write_csv(candidates, args.output)
        print(f"CSV written to {output_path}")

    except GitHubError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
