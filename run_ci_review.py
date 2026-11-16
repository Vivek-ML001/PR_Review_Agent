import os
import sys
from backend import run_review

def main():
    pr_url = os.getenv("PR_URL")
    if not pr_url:
        print("Error: PR_URL environment variable is required.")
        sys.exit(1)

    print(f"Starting autonomous review for: {pr_url}")
    final, posted = run_review(pr_url, post=True)

    if final is None:
        print("Docs-only PR detected; review skipped.")
        return

    print(final)
    if not posted:
        print("Error: Failed to post review to GitHub.")
        sys.exit(1)

    print("Review successfully posted to GitHub PR!")

if __name__ == "__main__":
    main()