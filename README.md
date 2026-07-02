# GitHub Candidate Sourcing Script

This project finds public GitHub candidates who appear to be actively building in a target role and tech stack.

## What it does
- Searches public GitHub repositories for your role + stack terms.
- Builds a ranked list of candidate GitHub users.
- Weighs recent GitHub activity heavily so active builders rise to the top.
- Writes a CSV file for free by default.
- Can also write to Google Sheets when credentials are provided.
- The CSV file contains:
  - GitHub username
  - public email if available
  - link to their most relevant repository
  - one-line relevance summary
  - location if listed
- Optionally writes the same data to a Google Sheet when credentials are supplied.

## Quick start
1. Install dependencies:
   pip install -r requirements.txt
2. Run the script:
   python candidate_sourcing.py --role "founding engineer" --tech-stack "rust,python,cpp" --limit 10
3. Output file will be written to `output/candidates.csv`.

You can swap in any role you want, such as `founding engineer`, `data scientist`, or `backend engineer`, and any comma-separated tech stack.

## Free CSV-first workflow
This is the simplest free path:
1. Use the existing GitHub public API search.
2. Export the results to CSV at `output/candidates.csv`.
3. Run the script with just the role and tech stack:
   ```sh
   source .venv/bin/activate
   python candidate_sourcing.py --role "data scientist" --tech-stack "python,pandas,sql" --experience-years 3 --limit 5
   ```

This path is free and does not require any Google credentials. If you want more reliable results and a higher GitHub API limit, set `GITHUB_TOKEN` in `.env`.

## Optional free Google Sheets export
If you want the sheet to populate automatically, use a free Google Cloud project, a free service account, and enable:
- Google Sheets API
- Google Drive API

Then run:
```sh
source .venv/bin/activate
python candidate_sourcing.py \
  --role "software engineer" \
  --tech-stack "rust,python,cpp" \
  --limit 5 \
  --sheet-name "Candidate Sourcing Demo" \
  --credentials "/absolute/path/to/service-account.json"
```

## Google Sheets setup (free)
Follow these steps to create a Google service account and connect it to the script:

1. Open Google Cloud Console:
   https://console.cloud.google.com/
2. Create or select a project.
3. Enable these APIs:
   - Google Sheets API
   - Google Drive API
4. Go to IAM & Admin -> Service Accounts.
5. Create a new service account, for example: `candidate-sourcing-script`.
6. Grant it the role `Viewer` on the project (or keep the default roles).
7. Create a key for that service account and download the JSON file.
   - Choose `JSON` format.
   - Save it somewhere safe, for example in this workspace folder.
8. Open Google Sheets and create a blank spreadsheet that you want the script to use.
9. Share that spreadsheet with the service account email address from the JSON file.
   - Give it `Editor` access.
10. Set the credentials path and sheet name in your shell:
    ```sh
    export GOOGLE_SHEETS_CREDENTIALS_FILE="/absolute/path/to/service-account.json"
    export GOOGLE_SHEETS_SHEET_NAME="Candidate Sourcing Demo"
    ```
11. Run the script:
    ```sh
    source .venv/bin/activate
   python candidate_sourcing.py --role "founding engineer" --tech-stack "rust,python,cpp" --experience-years 3 --limit 5
    ```

If the sheet name does not exist yet, the script will create it automatically.

## Notes
- Only public GitHub data is used.
- Search quality improves when you start with specific roles and stacks.
