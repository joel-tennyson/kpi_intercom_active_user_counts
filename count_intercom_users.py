import requests
import json
import sys
import random
import time
import os
import uuid
from datetime import datetime

if len(sys.argv) < 2:
    print("Usage: python count_intercom_users.py <recency_days> [--test] [--tag]")
    print("  --test: Use sample data instead of querying Intercom API")
    print("  --tag: Tag 7S1 profiles with 'Recently Active on 7S1 Only' tag")
    sys.exit(1)

# Check for test mode and tagging mode
TEST_MODE = "--test" in sys.argv
TAG_MODE = "--tag" in sys.argv

if TEST_MODE:
    print("🧪 Running in TEST MODE - using sample data")
if TAG_MODE:
    print("🏷️  Tagging mode enabled - will tag 7S1 profiles")

# --- Configuration ---
RECENCY_DAYS = int(sys.argv[1])

# Try to get token from environment first, then a local config file.
def get_token():
    # First, try to get the token from an environment variable (used for deployment).
    token = os.environ.get('INTERCOM_TOKEN')
    if token:
        return token
    
    # As a fallback for local testing, try to load from config.json.
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            return config.get('intercom_token')
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    
    # If neither works, exit with error
    print("Error: No Intercom token found. Set the INTERCOM_TOKEN environment variable or create config.json for local testing.", file=sys.stderr)
    sys.exit(1)

def get_config():
    """Load configuration, prioritizing environment variables over config.json."""
    config = {}
    
    # Load from environment variables (used for deployment)
    coda_webhook = os.environ.get('CODA_WEBHOOK_URL')
    if coda_webhook:
        config['coda_webhook_url'] = coda_webhook
    
    coda_token = os.environ.get('CODA_API_TOKEN')
    if coda_token:
        config['coda_api_token'] = coda_token
    
    # For any values not found in the environment, fall back to config.json (for local testing).
    try:
        with open('config.json', 'r') as f:
            file_config = json.load(f)
            # Only use file config if environment variable was not already set
            if 'coda_webhook_url' not in config:
                config['coda_webhook_url'] = file_config.get('coda_webhook_url')
            if 'coda_api_token' not in config:
                config['coda_api_token'] = file_config.get('coda_api_token')
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    return config

def tag_batch_of_users(user_ids, tag_name):
    """Tag a batch of users with the specified tag name."""
    url = "https://api.intercom.io/tags"
    
    payload = {
        "name": tag_name,
        "users": [{"id": user_id} for user_id in user_ids]
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Intercom-Version": "2.14"
    }
    
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()

def tag_7s1_profiles_in_batches(profile_ids, tag_name="Recently Active on 7S1 Only", batch_size=50):
    """Tag 7S1 profiles in batches with rate limiting and error handling."""
    if not profile_ids:
        print("No 7S1 profiles to tag.")
        return 0, 0
    
    total_profiles = len(profile_ids)
    successful_tags = 0
    failed_batches = 0
    
    print(f"\nTagging {total_profiles} 7S1 profiles in batches of {batch_size}...")
    
    for i in range(0, total_profiles, batch_size):
        batch = profile_ids[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total_profiles + batch_size - 1) // batch_size
        
        try:
            # Make the API call
            tag_batch_of_users(batch, tag_name)
            successful_tags += len(batch)
            print(f"✓ Tagged batch {batch_num}/{total_batches}: {len(batch)} profiles")
            
        except requests.exceptions.RequestException as e:
            print(f"✗ Failed batch {batch_num}/{total_batches}: {e}")
            failed_batches += 1
            
            # Handle rate limiting specifically
            if hasattr(e, 'response') and e.response.status_code == 429:
                retry_after = int(e.response.headers.get("Retry-After", 10))
                print(f"  Rate limited. Waiting {retry_after}s before continuing...")
                time.sleep(retry_after)
            
        # Rate limiting: wait between batches (except for the last one)
        if i + batch_size < total_profiles:
            time.sleep(2)  # 2 second delay between batches
    
    print(f"Tagging complete: {successful_tags} profiles tagged, {failed_batches} batches failed")
    return successful_tags, failed_batches

def send_to_coda(data, webhook_url, api_token):
    """Send data to Coda webhook, transforming it into an array of counts."""

    counts_array = []
    # Map internal category names to the desired display names for Coda
    category_map = {
        "only_7s2": "7S2",
        "only_7s1": "7S1",
        "both": "Both"
    }
    subscriptions = ["Unknown", "Admin", "Coach", "Live", "Core", "Free"]

    for internal_name, display_name in category_map.items():
        if internal_name not in data:
            continue
        for subscription in subscriptions:
            # Regular count
            regular_count = data[internal_name]["subscription_breakdown"][subscription]["regular"]
            counts_array.append({
                "category": display_name,
                "subscription": subscription,
                "fee_waiver": False,
                "total": regular_count,
            })

            # Fee waiver count
            fee_waiver_count = data[internal_name]["subscription_breakdown"][subscription]["fee_waiver"]
            counts_array.append({
                "category": display_name,
                "subscription": subscription,
                "fee_waiver": True,
                "total": fee_waiver_count,
            })

    # The main payload sent to Coda
    coda_payload = {
        "run_id": data["run_id"],
        "timestamp": data["timestamp"],
        "recency_days": RECENCY_DAYS,
        "counts": counts_array,
    }

    # Include tagging results if available
    if "tagging_results" in data:
        coda_payload["tagging_results"] = data["tagging_results"]

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(webhook_url, json=coda_payload, headers=headers, timeout=30)
    response.raise_for_status()
    print("✓ Successfully sent data to Coda webhook")

TOKEN = get_token()
API_URL = "https://api.intercom.io/contacts/search"
PER_PAGE = 150

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# Subscription mapping and ranking
SUBSCRIPTION_RANKS = {
    # 7S2 values
    "admin": 5,
    "Administrator": 5,
    "Staff": 5,
    "coach": 4,
    "live": 3,
    "core": 2,
    "free": 1,
    # 7S1 values
    "Coaching": 4,
    "Live": 3,
    "Yearly + Live": 3,
    "Core": 2,
    "Free Trial": 1
}

def get_subscription_rank(user, is_7s2):
    """Get the subscription rank for a user, returning 0 if unknown"""
    if is_7s2:
        sub_val = user.get("custom_attributes", {}).get("sub")
    else:
        sub_val = user.get("custom_attributes", {}).get("lsat_course")
    if sub_val in (None, ""):
        return 0  # Unknown
    return SUBSCRIPTION_RANKS.get(sub_val, 0)

def get_highest_subscription(users_7s1, users_7s2):
    """Get the highest subscription rank across both 7S1 and 7S2 profiles"""
    max_rank = 0
    for user in users_7s1:
        rank = get_subscription_rank(user, is_7s2=False)
        max_rank = max(max_rank, rank)
    for user in users_7s2:
        rank = get_subscription_rank(user, is_7s2=True)
        max_rank = max(max_rank, rank)
    return max_rank

def rank_to_subscription(rank):
    """Convert rank back to subscription name"""
    rank_map = {5: "Admin", 4: "Coach", 3: "Live", 2: "Core", 1: "Free", 0: "Unknown"}
    return rank_map.get(rank, "Unknown")

def is_fee_waiver(user):
    """Check if a user has a fee waiver via tags or purchase names."""
    
    # The ID for the fee waiver tag is 11173348
    FEE_WAIVER_TAG_ID = "11173348"
    tags = user.get("tags", {}).get("data", [])
    if any(tag.get("id") == FEE_WAIVER_TAG_ID for tag in tags):
        return True
    
    # Check for 'waiver' in lsat_purchase_names (for 7S1 users)
    purchase_names = user.get("custom_attributes", {}).get("lsat_purchase_names", "")
    return isinstance(purchase_names, str) and "waiver" in purchase_names.lower()

def fetch_all_users(start_query_timestamp):
    """
    Fetches all users from a backdated start time, with robust error handling.
    """
    all_users = []
    starting_after = None
    page = 1
    
    # Error handling config
    max_retries = 5
    retry_count = 0
    
        filter_block = [
            {"field": "role", "operator": "=", "value": "user"},
        {"field": "email", "operator": "!=", "value": None},
        {"field": "external_id", "operator": "!=", "value": None},
        {"field": "last_seen_at", "operator": ">", "value": start_query_timestamp}
    ]
    
    print(f"Querying for users seen after day start: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(start_query_timestamp))}", flush=True)

    while True:
        body = { "query": {"operator": "AND", "value": filter_block}, "pagination": {"per_page": PER_PAGE} }
        if starting_after:
            body["pagination"]["starting_after"] = starting_after

        try:
        response = requests.post(API_URL, headers=headers, json=body)
            
            # Handle rate limiting with retries
            if response.status_code == 429:
                if retry_count >= max_retries:
                    print(f"Error: Exceeded max rate-limit retries ({max_retries}). Aborting.", file=sys.stderr)
                    sys.exit(1)
                
                retry_after = int(response.headers.get("Retry-After", 10))
                print(f"Rate limited. Retrying after {retry_after}s... (Attempt {retry_count + 1}/{max_retries})", flush=True)
                retry_count += 1
                time.sleep(retry_after)
                continue
            
            # Reset retry counter on a successful request
            retry_count = 0
            
            response.raise_for_status() # Raise an exception for other bad responses (4xx or 5xx)
        data = response.json()

        except requests.exceptions.RequestException as e:
            print(f"\nError: A critical request error occurred: {e}", file=sys.stderr)
            sys.exit(1)
        
        if 'errors' in data:
            print(f"\nError: Intercom API returned an error: {json.dumps(data['errors'], indent=2)}", file=sys.stderr)
            sys.exit(1)
            
        users_on_page = data.get("data", [])
        all_users.extend(users_on_page)
        
        print(f"  - Page {page}: Fetched {len(users_on_page)} users (Total so far: {len(all_users)})", flush=True)
        page += 1
        
        next_page = data.get("pages", {}).get("next")
        if not next_page:
            break
        starting_after = next_page.get("starting_after")

    return all_users

def get_sample_data():
    """Return static sample data for testing Coda integration"""
    return {
        "total_unique_emails": 11007,
        "total_profiles_in_window": 11918,
        "emails_with_multiple_profiles": 909,
        "only_7s2": {
            "count": 2020,
            "sample": ["test.user1@example.com", "test.user2@example.com"],
            "subscription_breakdown": {
                "Unknown": {"regular": 0, "fee_waiver": 0},
                "Admin": {"regular": 0, "fee_waiver": 0},
                "Coach": {"regular": 33, "fee_waiver": 0},
                "Live": {"regular": 655, "fee_waiver": 142},
                "Core": {"regular": 684, "fee_waiver": 55},
                "Free": {"regular": 451, "fee_waiver": 0}
            }
        },
        "only_7s1": {
            "count": 8090,
            "sample": ["test.user3@example.com", "test.user4@example.com"],
            "subscription_breakdown": {
                "Unknown": {"regular": 1, "fee_waiver": 0},
                "Admin": {"regular": 3, "fee_waiver": 0},
                "Coach": {"regular": 178, "fee_waiver": 2},
                "Live": {"regular": 1467, "fee_waiver": 584},
                "Core": {"regular": 4991, "fee_waiver": 26},
                "Free": {"regular": 795, "fee_waiver": 43}
            }
        },
        "both": {
            "count": 897,
            "total_profiles_in_this_category": 1796,
            "sample": ["test.user5@example.com", "test.user6@example.com"],
            "subscription_breakdown": {
                "Unknown": {"regular": 0, "fee_waiver": 0},
                "Admin": {"regular": 13, "fee_waiver": 0},
                "Coach": {"regular": 21, "fee_waiver": 0},
                "Live": {"regular": 252, "fee_waiver": 78},
                "Core": {"regular": 338, "fee_waiver": 5},
                "Free": {"regular": 187, "fee_waiver": 3}
            }
        }
    }

# --- Main Execution ---

if TEST_MODE:
    # Use sample data for testing
    result = get_sample_data()
    print("Using static sample data for testing")
    only_7s1_profile_ids = []  # No real profile IDs in test mode
else:
    # 1. Calculate Timestamps
    now = int(time.time())
    # This is the precise start of our 24*N hour window
    min_last_seen_timestamp = now - (RECENCY_DAYS * 86400)

    # To work around the API, we find the start of the day *before* our window begins
    day_of_window_start = int(time.mktime(time.gmtime(min_last_seen_timestamp)[:3] + (0,0,0,0,0,0)))
    query_start_timestamp = day_of_window_start - 86400 # Start query from the day before

    print(f"Recency window: {RECENCY_DAYS} day(s)")
    print(f"Counting users seen after: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(min_last_seen_timestamp))}")
    print(f"API Query will fetch users from: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(day_of_window_start))}\n")

    # 2. Fetch all users using the backdated query
    all_users_from_api = fetch_all_users(query_start_timestamp)

    # 3. Manually filter for the precise time window
    accurate_users = [
        user for user in all_users_from_api 
        if user.get("last_seen_at", 0) > min_last_seen_timestamp
    ]
    print(f"\nFetched {len(all_users_from_api)} total profiles from API.")
    print(f"Found {len(accurate_users)} profiles matching the precise {RECENCY_DAYS*24}-hour window.")

    # 4. Process accurately filtered users
    all_users_by_email = {}
    for user in accurate_users:
        email = user.get("email")
        if not email:
            continue
        
        external_id = user.get("external_id")
        group = "Other" # Default
        if external_id:
            if external_id.startswith("usr"):
                group = "7S2"
            else:
                group = "7S1"
        
        if email not in all_users_by_email:
            all_users_by_email[email] = {"7S1": [], "7S2": [], "Other": []}
        
        all_users_by_email[email][group].append(user)

    # 5. Categorize emails and get subscription counts
    only_7s2, only_7s1, both = [], [], []
    emails_with_multiple_profiles = 0
    profiles_in_both_category = 0
    
    # For tagging: collect 7S1 profile IDs from users in the "only_7s1" category
    only_7s1_profile_ids = []

    subscription_buckets = ["Unknown", "Admin", "Coach", "Live", "Core", "Free"]
    subscription_counts = {
        "only_7s2": {sub: {"regular": 0, "fee_waiver": 0} for sub in subscription_buckets},
        "only_7s1": {sub: {"regular": 0, "fee_waiver": 0} for sub in subscription_buckets},
        "both": {sub: {"regular": 0, "fee_waiver": 0} for sub in subscription_buckets}
    }

for email, users in all_users_by_email.items():
        s1_profile_count = len(users["7S1"])
        s2_profile_count = len(users["7S2"])
        total_profiles_for_email = s1_profile_count + s2_profile_count

        if total_profiles_for_email > 1:
            emails_with_multiple_profiles += 1

        has_active_7s1 = s1_profile_count > 0
        has_active_7s2 = s2_profile_count > 0
    
    # Get highest subscription across both profiles
    highest_rank = get_highest_subscription(users["7S1"], users["7S2"])
    subscription = rank_to_subscription(highest_rank)
    
        # Determine if this email is a fee waiver
        fee_waiver = False
        for user in users["7S1"] + users["7S2"]:
            if is_fee_waiver(user):
                fee_waiver = True
                break

        if has_active_7s2 and not has_active_7s1:
            only_7s2.append(email)
            if fee_waiver:
                subscription_counts["only_7s2"][subscription]["fee_waiver"] += 1
            else:
                subscription_counts["only_7s2"][subscription]["regular"] += 1
        elif has_active_7s1 and not has_active_7s2:
            only_7s1.append(email)
            # Collect 7S1 profile IDs for tagging
            for user in users["7S1"]:
                user_id = user.get("id")
                if user_id:
                    only_7s1_profile_ids.append(user_id)
            if fee_waiver:
                subscription_counts["only_7s1"][subscription]["fee_waiver"] += 1
            else:
                subscription_counts["only_7s1"][subscription]["regular"] += 1
        elif has_active_7s1 and has_active_7s2:
            both.append(email)
            profiles_in_both_category += total_profiles_for_email
            if fee_waiver:
                subscription_counts["both"][subscription]["fee_waiver"] += 1
            else:
                subscription_counts["both"][subscription]["regular"] += 1

random.shuffle(only_7s2)
random.shuffle(only_7s1)
random.shuffle(both)

    # 6. Prepare and print final result
result = {
        "total_unique_emails": len(all_users_by_email),
        "total_profiles_in_window": len(accurate_users),
        "emails_with_multiple_profiles": emails_with_multiple_profiles,
    "only_7s2": {
        "count": len(only_7s2),
        "sample": only_7s2[:10],
        "subscription_breakdown": subscription_counts["only_7s2"]
    },
    "only_7s1": {
        "count": len(only_7s1),
        "sample": only_7s1[:10],
        "subscription_breakdown": subscription_counts["only_7s1"]
    },
    "both": {
        "count": len(both),
            "total_profiles_in_this_category": profiles_in_both_category,
        "sample": both[:10],
        "subscription_breakdown": subscription_counts["both"]
        }
}

print("\n--- Final Results ---")
print(json.dumps(result, indent=2))

# 8. Tag 7S1 profiles if tagging mode is enabled
tagging_results = None
if TAG_MODE and not TEST_MODE:
    if only_7s1_profile_ids:
        print(f"\n--- Tagging 7S1 Profiles ---")
        successful_tags, failed_batches = tag_7s1_profiles_in_batches(only_7s1_profile_ids)
        tagging_results = {
            "total_profiles_to_tag": len(only_7s1_profile_ids),
            "successfully_tagged": successful_tags,
            "failed_batches": failed_batches
        }
        result["tagging_results"] = tagging_results
    else:
        print("\n--- No 7S1 profiles to tag ---")
        tagging_results = {
            "total_profiles_to_tag": 0,
            "successfully_tagged": 0,
            "failed_batches": 0
        }
        result["tagging_results"] = tagging_results
elif TAG_MODE and TEST_MODE:
    print("\n--- Tagging skipped in TEST MODE ---") 

# 7. Send results to Coda
config = get_config()
webhook_url = config.get("coda_webhook_url")
api_token = config.get("coda_api_token")
if webhook_url and api_token:
    run_id = str(uuid.uuid4())
    result["run_id"] = run_id
    result["timestamp"] = int(time.time())  # Epoch seconds
    try:
        send_to_coda(result, webhook_url, api_token)
        print(f"Results sent to Coda with run ID: {run_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to send data to Coda webhook: {e}", file=sys.stderr)
        sys.exit(1)
else:
    print("Warning: No Coda webhook URL or API token configured. Results not sent to Coda.") 