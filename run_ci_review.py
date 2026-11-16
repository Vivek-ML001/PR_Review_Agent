import os
import sys
from backend import run_pr_review  # Import your compiled LangGraph invocation function

def main():
    pr_url = os.getenv("PR_URL")
    github_token = os.getenv("GITHUB_TOKEN")

    if not pr_url or not github_token:
        print("Error: PR_URL and GITHUB_TOKEN environment variables are required.")
        sys.exit(1)

    print(f"Starting autonomous review for: {pr_url}")
    result = run_pr_review(
        pr_url=pr_url,
        github_token=github_token,
        post_comment=True,
    )
    print(f"Review complete. Posted {len(result.findings)} inline findings.")

if __name__ == "__main__":
    main()