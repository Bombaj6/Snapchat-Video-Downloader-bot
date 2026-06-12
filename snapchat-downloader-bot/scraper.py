import requests
import json
import re
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

EXPANSION_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Upgrade-Insecure-Requests": "1"
}

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1"
}

def expand_url(url: str) -> str:
    """Expand shortened snapchat.com/t/ or t.snapchat.com links by following redirects up to 5 hops."""
    if "t.snapchat.com" in url or "snapchat.com/t/" in url:
        logging.info(f"Expanding short URL: {url}")
        from urllib.parse import urljoin
        current_url = url
        try:
            for _ in range(5):
                response = requests.get(current_url, headers=EXPANSION_HEADERS, allow_redirects=False, timeout=10)
                location = response.headers.get("Location")
                if not location:
                    break
                if location.startswith("/"):
                    current_url = urljoin(current_url, location)
                else:
                    current_url = location
            logging.info(f"Expanded to: {current_url}")
            return current_url
        except Exception as e:
            logging.error(f"Error expanding URL {url}: {e}")
    return url

def find_key_recursive(data, target_key):
    """Recursively search for a key in a nested dictionary/list structure."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == target_key and v:
                yield v
            yield from find_key_recursive(v, target_key)
    elif isinstance(data, list):
        for item in data:
            yield from find_key_recursive(item, target_key)

def clean_description(text: str) -> str:
    """Remove boilerplate text from Snapchat descriptions."""
    if not text:
        return ""
    boilerplate = "Another Spotlight Snap brought to you by Snapchat"
    if boilerplate in text:
        text = text.replace(boilerplate, "").strip()
    return text

def parse_input(input_str: str) -> dict:
    """
    Parse the user input to classify it.
    Returns:
        - {"type": "spotlight", "url": expanded_url, "id": id}
        - {"type": "profile", "username": username}
        - None (if invalid)
    """
    input_str = input_str.strip()
    
    # If it is a URL, expand it if needed
    if input_str.startswith("http"):
        expanded = expand_url(input_str)
        
        # Check for Spotlight
        spotlight_match = re.search(r'snapchat\.com/spotlight/([a-zA-Z0-9_-]+)', expanded)
        if spotlight_match:
            return {"type": "spotlight", "url": expanded, "id": spotlight_match.group(1)}
            
        # Check for profile add or story link (matching /add/ or /@)
        profile_match = re.search(r'snapchat\.com/(?:add/|@)([a-zA-Z0-9._-]{3,30})', expanded)
        if profile_match:
            return {"type": "profile", "username": profile_match.group(1)}
    else:
        # Check if it looks like a username directly (e.g. @username or username)
        clean_user = input_str[1:] if input_str.startswith("@") else input_str
        if re.match(r'^[a-zA-Z0-9._-]{3,30}$', clean_user):
            return {"type": "profile", "username": clean_user}
            
    return None

def extract_snapchat_content(input_str: str) -> dict:
    """
    Unified entrypoint to extract stories or spotlight video.
    """
    parsed = parse_input(input_str)
    if not parsed:
        return {
            "success": False,
            "error": "Invalid input. Please send a valid Snapchat link or username."
        }
        
    if parsed["type"] == "spotlight":
        return extract_spotlight(parsed["url"], parsed["id"])
    else:
        return extract_profile_stories(parsed["username"])

def extract_spotlight(url: str, video_id: str) -> dict:
    logging.info(f"Extracting Spotlight: {url}")
    try:
        response = requests.get(url, headers=SCRAPE_HEADERS, timeout=10)
        if response.status_code != 200:
            return {"success": False, "error": f"Failed to load page (Status code: {response.status_code})"}
            
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', response.text, re.DOTALL)
        if not match:
            return {"success": False, "error": "Could not extract video data."}
            
        json_data = json.loads(match.group(1))
        page_props = json_data.get("props", {}).get("pageProps", {})
        
        video_meta = page_props.get("videoMetadata")
        video_url = None
        title = ""
        description = ""
        creator_username = ""
        
        if video_meta:
            video_url = video_meta.get("contentUrl")
            title = video_meta.get("name", "")
            description = clean_description(video_meta.get("description", ""))
            creator = video_meta.get("creator")
            if isinstance(creator, dict):
                creator_username = creator.get("personCreator", {}).get("username", "")
            elif isinstance(creator, str):
                creator_username = creator
        
        # Fallback to spotlight feed
        if not video_url:
            stories = page_props.get("spotlightFeed", {}).get("spotlightStories", [])
            if stories:
                meta = stories[0].get("metadata", {}).get("videoMetadata", {})
                video_url = meta.get("contentUrl")
                title = meta.get("name", "")
                description = clean_description(meta.get("description", ""))
                creator_username = meta.get("creator", {}).get("personCreator", {}).get("username", "")
                
        # Recursive fallback
        if not video_url:
            content_urls = list(find_key_recursive(json_data, "contentUrl"))
            media_urls = list(find_key_recursive(json_data, "mediaUrl"))
            cdn_urls = [u for u in (content_urls + media_urls) if isinstance(u, str) and "cf-st.sc-cdn.net" in u]
            if cdn_urls:
                video_url = cdn_urls[0]
            
        if not video_url:
            return {"success": False, "error": "Direct video URL not found."}
            
        return {
            "success": True,
            "type": "spotlight",
            "stories": [{
                "media_url": video_url,
                "type": "video",
                "title": title,
                "description": description,
                "snap_id": video_id,
                "timestamp": 0
            }]
        }
    except Exception as e:
        return {"success": False, "error": f"Error scraping Spotlight: {str(e)}"}

def extract_profile_stories(username: str) -> dict:
    url = f"https://www.snapchat.com/add/{username}"
    logging.info(f"Extracting Profile Stories: {url}")
    try:
        response = requests.get(url, headers=SCRAPE_HEADERS, timeout=10)
        if response.status_code != 200:
            return {"success": False, "error": f"Failed to load user profile (Status code: {response.status_code})"}
            
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', response.text, re.DOTALL)
        if not match:
            return {"success": False, "error": "Could not extract profile data."}
            
        json_data = json.loads(match.group(1))
        page_props = json_data.get("props", {}).get("pageProps", {})
        
        # Get uploader display name info
        user_profile = page_props.get("userProfile", {})
        display_name = ""
        if isinstance(user_profile, dict):
            display_name = user_profile.get("userInfo", {}).get("displayName", "")
            username = user_profile.get("userInfo", {}).get("username", username)
            
        # Get stories list
        story_obj = page_props.get("story")
        if not story_obj or not isinstance(story_obj, dict):
            return {"success": False, "error": f"User '{username}' has no active public stories right now."}
            
        snap_list = story_obj.get("snapList", [])
        if not snap_list:
            return {"success": False, "error": f"User '{username}' has no active public stories right now."}
            
        stories = []
        for snap in snap_list:
            media_urls = snap.get("snapUrls", {})
            media_url = media_urls.get("mediaUrl")
            if not media_url:
                continue
                
            media_type_code = snap.get("snapMediaType", 1)
            media_type = "video" if media_type_code == 1 else "image"
            
            snap_id = snap.get("snapId", {}).get("value", "")
            timestamp = 0
            ts_sec = snap.get("timestampInSec", {})
            if ts_sec and isinstance(ts_sec, dict):
                timestamp = int(ts_sec.get("value", 0))
                
            stories.append({
                "media_url": media_url,
                "type": media_type,
                "title": "",
                "description": "",
                "snap_id": snap_id,
                "timestamp": timestamp
            })
            
        if not stories:
            return {"success": False, "error": f"User '{username}' has no active public stories right now."}
            
        return {
            "success": True,
            "type": "profile",
            "username": username,
            "display_name": display_name,
            "stories": stories
        }
    except Exception as e:
        return {"success": False, "error": f"Error scraping profile: {str(e)}"}
