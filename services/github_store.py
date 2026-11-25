"""Read and save one small text file in the GitHub repo (GitHub's contents API). No Streamlit imports.

Streamlit Cloud forgets files the app writes, so the watchlist is saved back to the repo as a
commit instead. Needs a fine-grained GitHub token with "Contents: read and write" on this
repo only, stored in the app's secrets as GITHUB_TOKEN.
"""
import base64

import requests

API = "https://api.github.com"
TIMEOUT = 10


class GitHubStoreError(Exception):
    """A problem saving to GitHub, with a message that is safe to show the user."""


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _explain(resp) -> str:
    if resp.status_code in (401, 403):
        return ("GitHub refused the token. Check that GITHUB_TOKEN in the app's secrets is still valid "
                "and has Contents read/write access to the setlistr repo.")
    if resp.status_code == 409:
        return "The file changed on GitHub at the same moment. Click save again."
    return f"GitHub returned an error ({resp.status_code})."


def read_file(repo: str, path: str, token: str, branch: str = "main"):
    """(text, sha) of a file on the branch; ('', None) if it doesn't exist yet."""
    try:
        resp = requests.get(f"{API}/repos/{repo}/contents/{path}", params={"ref": branch},
                            headers=_headers(token), timeout=TIMEOUT)
    except requests.RequestException:
        raise GitHubStoreError("Couldn't reach GitHub. Try again in a minute.")
    if resp.status_code == 404:
        return "", None
    if not resp.ok:
        raise GitHubStoreError(_explain(resp))
    data = resp.json()
    return base64.b64decode(data.get("content", "")).decode("utf-8"), data.get("sha")


def write_file(repo: str, path: str, token: str, text: str, sha, message: str,
               branch: str = "main") -> str:
    """Commit new contents for the file. sha must be the one read_file returned. Returns the new sha."""
    body = {"message": message, "branch": branch,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
    if sha:
        body["sha"] = sha
    try:
        resp = requests.put(f"{API}/repos/{repo}/contents/{path}", json=body,
                            headers=_headers(token), timeout=TIMEOUT)
    except requests.RequestException:
        raise GitHubStoreError("Couldn't reach GitHub. Your change wasn't saved; try again.")
    if not resp.ok:
        raise GitHubStoreError(_explain(resp))
    return resp.json().get("content", {}).get("sha", "")
