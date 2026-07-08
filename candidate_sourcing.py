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
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
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

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

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
        required=False,
        default="",
        help="Comma-separated tech stack, e.g. rust,python,cpp (optional)",
    )
    parser.add_argument("--limit", type=int, default=10, help="Number of candidates to return")
    parser.add_argument(
        "--all-locations",
        dest="all_locations",
        action="store_true",
        help="Include candidates from any location instead of only US/Canada.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="CSV file path for results",
    )
    parser.add_argument(
        "--sheet-name",
        default=os.getenv("GOOGLE_SHEETS_SHEET_NAME", "Candidate Sourcing"),
        help="Google Sheet name to write results to (default: 'Candidate Sourcing')",
    )
    parser.add_argument(
        "--credentials",
        default=os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json"),
        help="Path to Google OAuth or service account JSON (default: credentials.json)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not automatically open the Google Sheet in the browser after writing",
    )
    return parser.parse_args()


def make_request(url: str, params: Dict[str, object] | None = None, _retries: int = 3) -> Dict | List:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "candidate-sourcing-script",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 403 and "rate limit" in response.text.lower():
        if _retries <= 0:
            raise GitHubError("GitHub API rate limit exceeded. Too many retries.")
        reset_ts = response.headers.get("X-RateLimit-Reset")
        wait = max(int(reset_ts) - int(time.time()), 0) + 2 if reset_ts else 62
        print(f"  Rate limited — waiting {wait}s then retrying...", file=sys.stderr)
        time.sleep(wait)
        return make_request(url, params, _retries - 1)

    if response.status_code >= 400:
        raise GitHubError(f"GitHub API request failed: {response.status_code} {response.text[:200]}")

    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining and int(remaining) < 3:
        reset_ts = response.headers.get("X-RateLimit-Reset")
        wait = max(int(reset_ts) - int(time.time()), 0) + 2 if reset_ts else 62
        print(f"  Rate limit low ({remaining} left) — waiting {wait}s...", file=sys.stderr)
        time.sleep(wait)

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

    stack_query = " ".join(clean_stack)
    first_stack = clean_stack[0] if clean_stack else ""

    variants = [base_query]
    if clean_stack:
        variants.extend([
            f'"{clean_role}" "{first_stack}"',
            f'"{clean_role}" {first_stack}',
            f'"{clean_role}" developer {stack_query}',
            f'"{clean_role}" engineer {stack_query}',
            f'"{clean_role}" open source {stack_query}',
            stack_query,
            f'developer {stack_query}',
            f'engineer {stack_query}',
            f'{clean_role} {first_stack}',
        ])

    if experience_text:
        variants.append(f"{clean_role} {experience_text}")

    for query in list(variants):
        if query:
            variants.append(f"{query} in:readme")
            variants.append(f"{query} in:name,description")
            if language_terms:
                variants.append(f"{query} {' '.join(language_terms)}")
                variants.append(f"{query} in:readme {' '.join(language_terms)}")

    seen = set()
    unique_queries = []
    for item in variants:
        normalized = re.sub(r"\s+", " ", item).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_queries.append(item)
    return unique_queries


def build_user_query_variants(role: str, tech_stack: List[str], experience_years: int | None = None, us_only: bool = True) -> List[str]:
    clean_role = re.sub(r"\s+", " ", role).strip()
    clean_stack = [re.sub(r"\s+", " ", item).strip() for item in tech_stack if item.strip()]
    stack_query = " ".join(clean_stack)
    first_stack = clean_stack[0] if clean_stack else ""

    base_variants = []
    if clean_stack:
        base_variants.extend([
            stack_query,
            f"{clean_role} {first_stack}",
            f"{stack_query} developer",
            f"{stack_query} engineer",
        ])
    base_variants.append(clean_role)

    locations = ["location:United States", "location:Canada"] if us_only else [""]

    expanded = []
    for variant in base_variants:
        for loc in locations:
            q = f"{variant} {loc}".strip() if loc else variant
            expanded.append(q)

    seen = set()
    unique_queries = []
    for item in expanded:
        normalized = re.sub(r"\s+", " ", item).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_queries.append(item)
    return unique_queries


def build_fallback_query_variants(role: str, tech_stack: List[str], experience_years: int | None = None) -> List[str]:
    clean_role = re.sub(r"\s+", " ", role).strip()
    clean_stack = [re.sub(r"\s+", " ", item).strip() for item in tech_stack if item.strip()]

    variants = [clean_role, f"{clean_role} developer", f"{clean_role} engineer"]
    if clean_stack:
        variants.extend([
            " ".join(clean_stack),
            f"{clean_role} {' '.join(clean_stack)}",
            f"{clean_role} {clean_stack[0]}",
        ])

    for item in clean_stack:
        variants.append(item)

    if experience_years is not None:
        variants.append(f"{clean_role} {experience_years} years")

    seen = set()
    fallback_queries = []
    for item in variants:
        normalized = re.sub(r"\s+", " ", item).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            fallback_queries.append(item)
    return fallback_queries


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


def search_users(query: str, per_page: int = 10, page: int = 1) -> List[Dict]:
    """Search users using the public GitHub search API."""
    params = {
        "q": query,
        "sort": "followers",
        "order": "desc",
        "per_page": per_page,
        "page": page,
    }
    data = make_request(f"{GITHUB_API}/search/users", params)
    return data.get("items", []) if isinstance(data, dict) else []


def fetch_user(login: str) -> Dict:
    return make_request(f"{GITHUB_API}/users/{login}")


def fetch_user_repos(login: str, per_page: int = 3) -> List[Dict]:
    params = {"sort": "updated", "direction": "desc", "per_page": per_page}
    return make_request(f"{GITHUB_API}/users/{login}/repos", params)


_NOISE_REPO_NAMES = {
    "dotfiles", "config", "configs", "settings", "home", "setup",
    "profile", "resume", "cv", "about", "readme",
}


def _is_noise_repo(repo: Dict, owner_login: str = "") -> bool:
    name = (repo.get("name") or "").lower()
    if repo.get("fork"):
        return True
    if owner_login and name == owner_login.lower():
        return True
    if name in _NOISE_REPO_NAMES:
        return True
    if not repo.get("language") and not repo.get("stargazers_count"):
        return True
    return False


def pick_most_relevant_repo(repos: List[Dict], tech_stack: List[str], owner_login: str = "") -> Dict | None:
    if not repos:
        return None

    tech_set = {item.lower() for item in tech_stack}
    candidates = [r for r in repos if not _is_noise_repo(r, owner_login)]
    pool = candidates if candidates else repos

    def repo_rank(repo: Dict) -> Tuple[int, str, int]:
        score = 0
        language = (repo.get("language") or "").lower()
        name_text = f"{repo.get('name', '')} {repo.get('description') or ''}".lower()

        if language in tech_set:
            score += 20
        if any(term and term in name_text for term in tech_set):
            score += 10

        stars = repo.get("stargazers_count", 0)
        if stars:
            score += min(stars // 10, 10)

        pushed_at = repo.get("pushed_at") or ""
        return score, pushed_at, stars

    return max(pool, key=repo_rank)


def latest_push_days_old(repos: List[Dict]) -> int | None:
    latest_push = None
    for repo in repos:
        pushed_at = repo.get("pushed_at")
        if not pushed_at:
            continue
        try:
            pushed_at_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest_push is None or pushed_at_dt > latest_push:
            latest_push = pushed_at_dt

    if latest_push is None:
        return None

    return max(0, (datetime.now(timezone.utc) - latest_push).days)


def summarize_candidate(user: Dict, repos: List[Dict], role: str = "", tech_stack: List[str] | None = None) -> str:
    tech_stack = tech_stack or []
    tech_set = {t.lower() for t in tech_stack}
    bio = " ".join((user.get("bio") or "").split()).strip()

    matching_langs = sorted({
        (repo.get("language") or "")
        for repo in repos
        if (repo.get("language") or "").lower() in tech_set
    })
    all_langs = sorted({repo.get("language") for repo in repos if repo.get("language")})
    display_langs = matching_langs or all_langs[:3]

    bio_tech_matches = [t for t in tech_stack if bio and t.lower() in bio.lower()]

    parts: List[str] = []

    if matching_langs:
        parts.append(f"active in {', '.join(matching_langs)}")
    elif display_langs:
        parts.append(f"works in {', '.join(display_langs[:3])}")

    if bio_tech_matches and not matching_langs:
        parts.append(f"mentions {', '.join(bio_tech_matches[:3])} in bio")

    top_repos = [r.get("name") for r in repos[:3] if r.get("name")]
    if top_repos:
        parts.append(f"notable repos: {', '.join(top_repos[:2])}")

    if bio:
        condensed = bio if len(bio) <= 100 else bio[:97].rstrip() + "..."
        parts.append(condensed)

    role_label = role.strip() or "this role"
    if parts:
        return f"Relevant for {role_label} — {'; '.join(parts)}."
    return f"GitHub user with public repositories potentially relevant to {role_label}."


_US_STATE_ABBREVS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
}

_US_STATE_ABBREV_PATTERN = re.compile(
    r",\s*(?:" + "|".join(sorted(_US_STATE_ABBREVS, key=len, reverse=True)) + r")"
    r"(?:\s*\d{5}(?:-\d{4})?)?"
    r"(?:[,\s]+(?:us[a]?|u\.s\.(?:a\.?)?|united\s+states))?"
    r"\s*$",
    re.IGNORECASE,
)


def normalize_location(location: str) -> str:
    text = re.sub(r"\s+", " ", (location or "").strip())
    if not text:
        return ""

    lowered = text.lower()
    canada_markers = [
        "canada", "ontario", "quebec", "alberta", "british columbia", "nova scotia",
        "new brunswick", "manitoba", "saskatchewan", "ottawa", "toronto", "vancouver",
        "montreal", "calgary", "edmonton",
    ]
    us_markers = [
        "united states of america", "united states", "usa", "u.s.a.", "u.s.",
        "america", "new york", "california", "texas",
        "florida", "illinois", "pennsylvania", "ohio", "georgia", "north carolina",
        "new jersey", "virginia", "washington", "massachusetts", "arizona", "michigan",
        "indiana", "tennessee", "missouri", "maryland", "wisconsin", "colorado",
        "minnesota", "south carolina", "alabama", "louisiana", "kentucky", "oregon",
        "oklahoma", "connecticut", "iowa", "mississippi", "arkansas", "kansas", "utah",
        "nevada", "new mexico", "nebraska", "idaho", "hawaii", "maine", "montana",
        "delaware", "south dakota", "north dakota", "alaska", "vermont", "wyoming",
        "district of columbia",
        # major US cities
        "san francisco", "los angeles", "chicago", "houston", "phoenix",
        "philadelphia", "san antonio", "san diego", "dallas", "san jose",
        "austin", "seattle", "denver", "boston", "nashville", "baltimore",
        "portland", "las vegas", "atlanta", "raleigh", "minneapolis", "miami",
        "new orleans", "cleveland", "tampa", "pittsburgh", "cincinnati", "detroit",
        "salt lake city", "silicon valley", "bay area", "nyc", "new york city",
        "sf bay", "greater boston", "greater seattle", "greater chicago",
    ]

    if any(marker in lowered for marker in canada_markers):
        return "Canada"
    if any(marker in lowered for marker in us_markers):
        return "United States"

    if _US_STATE_ABBREV_PATTERN.search(text):
        return "United States"

    return text


def is_us_canada_location(location: str, bio: str | None = None) -> bool:
    raw_text = (location or "").strip().lower()
    if not raw_text:
        return False

    cleaned_text = re.sub(r"[^\w\s]", " ", raw_text)
    tokens = set(cleaned_text.split())

    precise_single_markers = {
        "usa", "us", "u.s.", "u.s.a.", "america",
        "canada", "ca", "dc",
    }
    precise_phrase_markers = {
        "united states of america", "united states", "new york", "north carolina",
        "new jersey", "south carolina", "rhode island", "new hampshire",
        "district of columbia", "new mexico", "south dakota", "north dakota",
        "prince edward", "british columbia", "new brunswick", "nova scotia",
        "newfoundland",
        # major US metro areas commonly used on GitHub
        "san francisco", "los angeles", "san diego", "san jose", "san antonio",
        "new orleans", "salt lake city", "kansas city", "st. louis", "fort worth",
        "las vegas", "silicon valley", "bay area", "sf bay", "new york city",
        "greater boston", "greater seattle", "greater chicago",
    }
    state_province_markers = {
        "california", "texas", "florida", "illinois", "pennsylvania",
        "ohio", "georgia", "virginia", "washington", "massachusetts",
        "arizona", "michigan", "indiana", "tennessee", "missouri",
        "maryland", "wisconsin", "colorado", "minnesota", "alabama",
        "louisiana", "kentucky", "oregon", "oklahoma", "connecticut",
        "iowa", "mississippi", "arkansas", "kansas", "utah", "nevada",
        "nebraska", "idaho", "hawaii", "maine", "montana", "delaware",
        "alaska", "vermont", "wyoming",
        # major US cities
        "san francisco", "los angeles", "chicago", "houston", "phoenix",
        "philadelphia", "san antonio", "san diego", "dallas", "san jose",
        "austin", "jacksonville", "fort worth", "columbus", "charlotte",
        "indianapolis", "san francisco", "seattle", "denver", "boston",
        "nashville", "baltimore", "louisville", "portland", "las vegas",
        "milwaukee", "albuquerque", "tucson", "fresno", "sacramento",
        "mesa", "omaha", "atlanta", "raleigh", "minneapolis", "miami",
        "new orleans", "cleveland", "tampa", "pittsburgh", "cincinnati",
        "detroit", "salt lake city", "st. louis", "kansas city",
        "silicon valley", "bay area", "sf bay", "greater boston",
        "greater seattle", "greater chicago", "nyc", "new york city",
        # Canada
        "toronto", "vancouver", "montreal", "ottawa", "calgary", "edmonton",
        "quebec", "ontario", "alberta", "manitoba", "saskatchewan",
    }

    if any(re.search(rf"\b{re.escape(marker)}\b", cleaned_text) for marker in precise_single_markers):
        return True
    if any(marker in cleaned_text for marker in precise_phrase_markers):
        return True
    if bool(tokens & state_province_markers):
        return True
    return bool(_US_STATE_ABBREV_PATTERN.search(location or ""))


def is_us_location(location: str) -> bool:
    """Return True only for US locations, excluding Canada."""
    raw = (location or "").strip().lower()
    if not raw:
        return False

    canada_markers = [
        "canada", "ontario", "quebec", "alberta", "british columbia", "nova scotia",
        "new brunswick", "manitoba", "saskatchewan", "ottawa", "toronto", "vancouver",
        "montreal", "calgary", "edmonton", "prince edward", "newfoundland",
    ]
    if any(marker in raw for marker in canada_markers):
        return False

    return is_us_canada_location(location)


def match_label(score: int) -> str:
    if score >= 150:
        return "Strong match"
    if score >= 100:
        return "Good match"
    if score >= 60:
        return "Moderate match"
    return "Weak match"


def _is_qualified_candidate(user: Dict, repos: List[Dict]) -> Tuple[bool, str]:
    """Hard-filter only clear duds — orgs, total ghosts, and completely dead accounts."""
    if user.get("type") != "User":
        return False, "organization account"

    followers = user.get("followers", 0)
    public_repos = user.get("public_repos", 0)
    total_stars = sum(r.get("stargazers_count", 0) for r in repos)

    if followers == 0 and total_stars == 0 and public_repos < 2:
        return False, "ghost account"

    latest_days = latest_push_days_old(repos)
    if latest_days is not None and latest_days > 1095:
        return False, "inactive for 3+ years"

    return True, ""


def score_candidate(user: Dict, repos: List[Dict], matching_repo_count: int, tech_stack: List[str]) -> int:
    score = 0
    tech_set = {item.lower() for item in tech_stack}

    # Stack match in actual repos (not just bio mentions)
    stack_repo_count = sum(1 for r in repos if (r.get("language") or "").lower() in tech_set)
    score += min(stack_repo_count * 12, 48)
    score += min(matching_repo_count * 8, 32)

    # Follower count — logarithmic so 10k followers isn't 500x better than 20
    followers = user.get("followers", 0)
    if followers >= 1000:
        score += 40
    elif followers >= 500:
        score += 30
    elif followers >= 100:
        score += 20
    elif followers >= 20:
        score += 10
    elif followers >= 5:
        score += 5

    # Total stars across all repos — biggest signal of real, useful work
    total_stars = sum(r.get("stargazers_count", 0) for r in repos)
    if total_stars >= 1000:
        score += 50
    elif total_stars >= 100:
        score += 30
    elif total_stars >= 20:
        score += 15
    elif total_stars >= 5:
        score += 5

    # Professional signals
    if user.get("company"):
        score += 15
    if user.get("hireable"):
        score += 10
    if user.get("blog"):
        score += 5
    if user.get("email"):
        score += 5

    # Account age — established accounts are more credible
    created_at = user.get("created_at")
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_years = (datetime.now(timezone.utc) - created).days / 365
            if age_years >= 7:
                score += 20
            elif age_years >= 4:
                score += 12
            elif age_years >= 2:
                score += 6
        except ValueError:
            pass

    # Recency — how recently they pushed code
    latest_days_old = latest_push_days_old(repos)
    if latest_days_old is not None:
        if latest_days_old <= 7:
            score += 40
        elif latest_days_old <= 30:
            score += 30
        elif latest_days_old <= 90:
            score += 20
        elif latest_days_old <= 180:
            score += 10
        elif latest_days_old <= 365:
            score += 2
        else:
            score -= 15

    return score


def _paginate_user_search(query: str, seen: set, target: int) -> List[Dict]:
    """Run a single user search query across up to 10 pages (GitHub's 1000-result max)."""
    results = []
    for page in range(1, 11):
        if len(seen) + len(results) >= target:
            break
        items = search_users(query, per_page=100, page=page)
        if not items:
            break
        results.extend(i for i in items if i.get("login") and i["login"] not in seen)
        if len(items) < 100:
            break
        time.sleep(1.0)
    return results


def _paginate_repo_search(query: str, max_pages: int = 5) -> List[Dict]:
    """Run a single repo search query across multiple pages."""
    results = []
    for page in range(1, max_pages + 1):
        items = search_repositories(query, per_page=100, page=page)
        if not items:
            break
        results.extend(items)
        if len(items) < 100:
            break
        time.sleep(1.0)
    return results


def build_candidates(role: str, tech_stack: List[str], limit: int = 10, experience_years: int | None = None, us_only: bool = True) -> List[Dict]:
    DISCOVERY_TARGET = max(300, limit * 4)
    ENRICH_LIMIT = max(limit * 2, 80)

    # login -> {followers, location, bio, search_score}
    login_pool: Dict[str, Dict] = {}
    repo_owner_counts: Dict[str, int] = defaultdict(int)

    def add_login(item: Dict) -> None:
        login = item.get("login")
        if login and login not in login_pool:
            login_pool[login] = {
                "followers": item.get("followers") or 0,
                "location": item.get("location") or "",
                "bio": item.get("bio") or "",
                "search_score": item.get("score") or 0,
            }

    # --- Phase 1: Discovery (cheap — no per-user API calls) ---
    print(f"[1/3] Discovering candidates...")

    user_queries = (
        build_user_query_variants(role, tech_stack, experience_years, us_only=us_only)
        + build_fallback_query_variants(role, tech_stack, experience_years)
    )
    for query in user_queries:
        if len(login_pool) >= DISCOVERY_TARGET:
            break
        for item in _paginate_user_search(query, set(login_pool.keys()), DISCOVERY_TARGET):
            add_login(item)

    # always run repo searches regardless of pool size — needed to populate repo_owner_counts
    repo_queries = (
        build_query_variants(role, tech_stack, experience_years)
        + build_fallback_query_variants(role, tech_stack, experience_years)
    )
    for query in repo_queries[:10]:
        for repo in _paginate_repo_search(query, max_pages=1):
            owner = repo.get("owner", {}).get("login")
            if owner:
                repo_owner_counts[owner] += 1
                if owner not in login_pool:
                    login_pool[owner] = {"followers": 0, "location": "", "bio": "", "search_score": 0}

    print(f"[1/3] Found {len(login_pool)} unique candidates.")

    # --- Phase 2: Pre-filter + pre-score using cheap search data ---
    print(f"[2/3] Pre-scoring and selecting top {ENRICH_LIMIT} to enrich...")

    pre_scored = []
    for login, data in login_pool.items():
        loc = (data.get("location") or "").strip()
        if us_only and loc and not is_us_canada_location(loc, data.get("bio")):
            continue
        # note: user search API doesn't return followers/bio, so don't ghost-filter here
        pre_score = (
            min(data.get("followers") or 0, 500) * 0.5
            + repo_owner_counts.get(login, 0) * 30
            + (data.get("search_score") or 0) * 0.1
        )
        pre_scored.append((login, pre_score))

    pre_scored.sort(key=lambda x: -x[1])
    top_logins = [login for login, _ in pre_scored]
    print(f"  {len(top_logins)} candidates passed pre-scoring.")

    # --- Phase 3: Parallel enrichment ---
    ENRICH_BATCH = min(len(top_logins), max(limit * 2, 200))
    enrich_logins = top_logins[:ENRICH_BATCH]
    print(f"[3/3] Enriching top {len(enrich_logins)} candidates in parallel...")

    def _enrich(login: str):
        try:
            return login, fetch_user(login), fetch_user_repos(login, per_page=30)
        except GitHubError as e:
            print(f"  API error for {login}: {e}", file=sys.stderr)
            return login, None, None

    enriched_map: Dict[str, tuple] = {}
    with ThreadPoolExecutor(max_workers=15) as executor:
        for login, user, repos in executor.map(_enrich, enrich_logins):
            if user is not None:
                enriched_map[login] = (user, repos)

    _dbg_api_errors = sum(1 for login in enrich_logins if login not in enriched_map)
    _dbg_location_rejected = 0
    _dbg_qual_rejected = 0

    candidates = []
    for login in enrich_logins:
        if len(candidates) >= limit:
            break
        if login not in enriched_map:
            continue
        user, user_repos = enriched_map[login]

        location = (user.get("location") or "").strip()
        if us_only and location and not is_us_canada_location(location, user.get("bio")):
            _dbg_location_rejected += 1
            continue

        repos_to_use = []
        seen_repo_urls: set = set()
        for repo in user_repos:
            repo_url = repo.get("html_url")
            if repo.get("name") and repo_url and repo_url not in seen_repo_urls:
                seen_repo_urls.add(repo_url)
                repos_to_use.append(repo)

        qualified, reason = _is_qualified_candidate(user, repos_to_use)
        if not qualified:
            _dbg_qual_rejected += 1
            continue

        matching_repo_count = repo_owner_counts.get(login, 0)
        best_repo = pick_most_relevant_repo(repos_to_use, tech_stack, owner_login=login)
        score = score_candidate(user, repos_to_use, matching_repo_count, tech_stack)
        normalized_location = normalize_location(user.get("location") or "")
        candidates.append({
            "username": user.get("login"),
            "profile_url": user.get("html_url") or f"https://github.com/{user.get('login')}",
            "public_email": user.get("email") or "",
            "most_relevant_repo": best_repo.get("html_url") if best_repo else (user.get("html_url") or ""),
            "relevance_summary": summarize_candidate(user, user_repos, role=role, tech_stack=tech_stack),
            "location": normalized_location,
            "score": score,
            "match_label": match_label(score),
            "last_activity_days": latest_push_days_old(user_repos),
            "followers": user.get("followers", 0),
            "public_repos": user.get("public_repos", 0),
            "bio": user.get("bio") or "",
        })

    candidates.sort(key=lambda item: (-item["score"], item.get("last_activity_days") or 10**9, item["username"]))
    print(f"[3/3] Done. API errors: {_dbg_api_errors} | Location rejected: {_dbg_location_rejected} | Qual rejected: {_dbg_qual_rejected} | Passed: {len(candidates)}")
    if len(candidates) < limit:
        print(f"Warning: only found {len(candidates)} of {limit} requested candidates.")
    return candidates


def write_csv(candidates: List[Dict], output_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "GitHub username",
        "GitHub profile",
        "Public email if available",
        "Link to their most relevant repository",
        "One line summary of why they are relevant",
        "Location if listed",
        "Match quality",
        "Score",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in candidates:
            writer.writerow({
                "GitHub username": item["username"],
                "GitHub profile": item.get("profile_url", ""),
                "Public email if available": item["public_email"],
                "Link to their most relevant repository": item["most_relevant_repo"],
                "One line summary of why they are relevant": item["relevance_summary"],
                "Location if listed": item["location"],
                "Match quality": item.get("match_label", ""),
                "Score": item["score"],
            })
    return path


def _open_google_client(credentials_file: str) -> "gspread.Client":
    """Return an authenticated gspread client, auto-detecting credential type."""
    if not gspread:
        raise RuntimeError("gspread is not installed. Run: pip install -r requirements.txt")

    cred_path = Path(credentials_file)
    if not cred_path.exists():
        raise RuntimeError(
            f"Credentials file not found: {credentials_file}\n"
            "Download your OAuth credentials from Google Cloud Console and save as credentials.json"
        )

    with cred_path.open() as f:
        cred_data = json.load(f)

    if cred_data.get("type") == "service_account":
        if not Credentials:
            raise RuntimeError("google-auth is not installed. Run: pip install -r requirements.txt")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        return gspread.authorize(credentials)

    # OAuth2 client credentials (Desktop app) — opens browser on first run, then reuses saved token
    return gspread.oauth(credentials_filename=credentials_file)


def write_to_google_sheet(
    candidates: List[Dict],
    sheet_name: str,
    credentials_file: str,
    open_in_browser: bool = True,
) -> None:
    client = _open_google_client(credentials_file)

    try:
        spreadsheet = client.open(sheet_name)
    except gspread.SpreadsheetNotFound:
        spreadsheet = client.create(sheet_name)

    worksheet = spreadsheet.sheet1
    worksheet.clear()

    headers = [
        "GitHub username",
        "GitHub profile",
        "Public email if available",
        "Link to their most relevant repository",
        "One line summary of why they are relevant",
        "Location if listed",
        "Match quality",
        "Score",
    ]
    rows = [headers] + [
        [
            item["username"],
            item.get("profile_url", ""),
            item["public_email"],
            item["most_relevant_repo"],
            item["relevance_summary"],
            item["location"],
            item.get("match_label", ""),
            item["score"],
        ]
        for item in candidates
    ]
    worksheet.update(rows, "A1")

    print(f"Google Sheet updated: {spreadsheet.url}")
    if open_in_browser:
        webbrowser.open(spreadsheet.url)


def main() -> None:
    args = parse_args()
    tech_stack = [item.strip() for item in args.tech_stack.split(",") if item.strip()]

    try:
        candidates = build_candidates(
            args.role,
            tech_stack,
            limit=args.limit,
            experience_years=args.experience_years,
            us_only=not args.all_locations,
        )
        if not candidates:
            print("No candidates found. Try a broader role/stack combination.")
            return

        if args.sheet_name and args.credentials and Path(args.credentials).exists():
            try:
                write_to_google_sheet(
                    candidates,
                    args.sheet_name,
                    args.credentials,
                    open_in_browser=not args.no_open,
                )
            except Exception as exc:
                print(f"Google Sheets export failed: {exc}", file=sys.stderr)
                output_path = write_csv(candidates, args.output)
                print(f"Fell back to CSV: {output_path}")
        else:
            output_path = write_csv(candidates, args.output)
            print(f"CSV written to {output_path}")
            if not Path(args.credentials).exists():
                print("Tip: add credentials.json to write directly to Google Sheets.")

    except GitHubError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
