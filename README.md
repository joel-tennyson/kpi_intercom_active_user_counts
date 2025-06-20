# Intercom User Count Script

This script counts active Intercom users and categorizes them by platform (7S1/7S2) and subscription type, with fee waiver detection. Results are automatically sent to a Coda webhook.

## Features

- Counts users active within a specified time window (in days)
- Categorizes users as 7S1-only, 7S2-only, or active in both platforms
- Detects fee waiver status via tags and purchase history
- Provides subscription breakdown for each category
- Handles API rate limiting with retries
- Works in both Replit and local environments
- **NEW**: Automatically sends results to Coda webhook with unique run ID

## Setup and Deployment

This script can be run locally for testing or deployed to run automatically.

### GitHub Actions (Recommended for Automation)

The most reliable and free way to run this script daily is with GitHub Actions.

1.  **Push to GitHub:** Make sure your project is pushed to a GitHub repository.
2.  **Add Secrets:** In your GitHub repository, go to `Settings` > `Secrets and variables` > `Actions`. Click `New repository secret` and add the following three secrets:
    *   `INTERCOM_TOKEN`: Your Intercom API token.
    *   `CODA_WEBHOOK_URL`: The webhook URL for your Coda table.
    *   `CODA_API_TOKEN`: The API token for your Coda account.
3.  **That's it!** The workflow defined in `.github/workflows/daily-run.yml` will now automatically run every day at 1:00 AM UTC. You can also trigger it manually from the "Actions" tab in your repository.

### For Local Testing

1.  Clone or download the files.
2.  Install dependencies: `pip install -r requirements.txt`
3.  Fill in your credentials in the `config.json` file.
4.  Run the script from your terminal.

### For Replit Deployment

Note: Running scheduled tasks on Replit requires a paid plan.

1.  Create a new Replit project.
2.  Upload the files: `count_intercom_users.py`, `requirements.txt`.
3.  In Replit, go to **Tools** → **Secrets**.
4.  Add the same three secrets listed in the GitHub Actions section.
5.  Set up a **Scheduled Deployment** to run the script daily.

## Usage

```bash
python count_intercom_users.py <recency_days> [--test]
```

Examples:
- `python count_intercom_users.py 1` - Count users active in the last 24 hours
- `python count_intercom_users.py 7` - Count users active in the last 7 days
- `python count_intercom_users.py 1 --test` - Test mode: use sample data, bypassing the Intercom API and sending a test payload to Coda.

### Test Mode

Use `--test` flag to test the Coda integration without making Intercom API calls:
- Generates realistic sample data with the same structure as real API responses
- Processes data through the same logic as production runs
- Sends results to Coda webhook for testing
- Much faster execution for development and testing

## Output

The script outputs JSON with:
- Total unique emails and profiles
- Breakdown by platform (7S1-only, 7S2-only, both)
- Subscription type distribution for each category
- Fee waiver counts
- Sample email addresses for verification
- **NEW**: Unique run ID and timestamp for tracking

## Coda Integration

Results are automatically sent to your configured Coda webhook with:
- All user count data
- Unique run ID (UUID) for tracking
- ISO timestamp of when the script ran
- Success/failure status in console output

## Token Priority

The script checks for credentials in this order:
1. Environment variables (Replit secrets)
2. Local `config.json` file
3. Exit with error if not found

## Requirements

- Python 3.6+
- `requests` library
- Valid Intercom API token with appropriate permissions
- Valid Coda webhook URL 