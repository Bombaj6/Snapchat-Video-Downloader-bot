import os
import re
import telebot
import requests
import logging
from datetime import datetime
from scraper import extract_snapchat_content, expand_url

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Read Telegram token from environment variable
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Error: TELEGRAM_BOT_TOKEN environment variable not set.")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "👻 **Snapchat Downloader Bot** 👻\n\n"
        "Send me a Snapchat Spotlight link, a Story link, or a Snapchat username, and I will download and send you the media directly!\n\n"
        "💡 **How to use:**\n"
        "• **Spotlight**: Send a link like `https://www.snapchat.com/spotlight/...`\n"
        "• **Profile/Story**: Send a link like `https://www.snapchat.com/add/username` or `https://snapchat.com/t/...`\n"
        "• **Username**: Send a raw username like `@djskhaled` or just `djskhaled`\n\n"
        "⚡ **Features:**\n"
        "• Automatic URL expansion\n"
        "• Supports both photos and videos in stories\n"
        "• Downloads all active stories for a user profile in one go!\n\n"
        "_Note: Only public content is supported._"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.strip()
    
    # Try to find a URL or determine if it is a username
    input_str = None
    url_match = re_search_url(text)
    
    if url_match:
        input_str = url_match
    else:
        # Check if it's a raw username (with optional leading @)
        clean_text = text[1:] if text.startswith("@") else text
        if re.match(r'^[a-zA-Z0-9._-]{3,30}$', clean_text):
            input_str = clean_text
            
    if not input_str:
        # Ignore message if it is not a URL or username
        return

    # Send initial status
    status_msg = bot.reply_to(message, "🔍 **Processing input... Please wait.**", parse_mode='Markdown')
    bot.send_chat_action(message.chat.id, 'typing')
    
    logging.info(f"Received download request from Chat {message.chat.id}: {input_str}")
    info = extract_snapchat_content(input_str)
    
    if not info.get("success"):
        error_text = f"❌ **Error:** {info.get('error', 'Failed to retrieve media.')}"
        bot.edit_message_text(error_text, message.chat.id, status_msg.message_id, parse_mode='Markdown')
        return
        
    stories = info.get("stories", [])
    total_count = len(stories)
    content_type = info.get("type") # "spotlight" or "profile"
    username = info.get("username", "")
    display_name = info.get("display_name", "")
    
    bot.edit_message_text(f"⚡ **Found {total_count} media item(s). Starting download...**", message.chat.id, status_msg.message_id, parse_mode='Markdown')
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    }
    
    for idx, story in enumerate(stories, 1):
        media_url = story.get("media_url")
        media_type = story.get("type") # "video" or "image"
        snap_id = story.get("snap_id", "")
        timestamp = story.get("timestamp", 0)
        
        ext = "mp4" if media_type == "video" else "jpg"
        temp_filename = f"temp_{message.chat.id}_{message.message_id}_{idx}.{ext}"
        
        try:
            bot.edit_message_text(
                f"📥 **Downloading item {idx} of {total_count}...**",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
            
            # Stream the media file
            response = requests.get(media_url, headers=headers, stream=True, timeout=20)
            response.raise_for_status()
            
            with open(temp_filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            # Check size limits (Telegram bot API limits local upload to 50MB)
            file_size_mb = os.path.getsize(temp_filename) / (1024 * 1024)
            if file_size_mb > 50:
                logging.warning(f"File {temp_filename} exceeds 50MB limit ({file_size_mb:.1f}MB)")
                bot.send_message(
                    message.chat.id,
                    f"⚠️ **Item {idx} of {total_count} is too large to upload (>50MB). Skipping.**",
                    parse_mode='Markdown',
                    reply_to_message_id=message.message_id
                )
                cleanup_file(temp_filename)
                continue
                
            bot.edit_message_text(
                f"📤 **Uploading item {idx} of {total_count} to Telegram...**",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
            
            # Trigger corresponding chat action
            chat_action = 'upload_video' if media_type == "video" else 'upload_photo'
            bot.send_chat_action(message.chat.id, chat_action)
            
            # Build caption
            caption_parts = []
            if content_type == "spotlight":
                title = story.get("title", "")
                desc = story.get("description", "")
                if title:
                    caption_parts.append(f"🎬 **{title}**")
                if desc and desc != title:
                    caption_parts.append(f"📝 {desc}")
            else:
                # Profile story caption
                header = f"👻 **Story {idx} of {total_count}**"
                caption_parts.append(header)
                
                # Creator info
                creator_str = f"👤 **User:** "
                if display_name:
                    creator_str += f"{display_name} "
                creator_str += f"(@{username})"
                caption_parts.append(creator_str)
                
                # Timestamp
                if timestamp > 0:
                    time_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    caption_parts.append(f"📅 **Date:** {time_str}")
                    
            caption_parts.append("\nDownloaded via @SnapchatDownloaderBot")
            caption = "\n".join(caption_parts)
            
            # Send file
            with open(temp_filename, 'rb') as media_file:
                if media_type == "video":
                    bot.send_video(
                        message.chat.id,
                        media_file,
                        caption=caption,
                        parse_mode='Markdown',
                        supports_streaming=True,
                        reply_to_message_id=message.message_id
                    )
                else:
                    bot.send_photo(
                        message.chat.id,
                        media_file,
                        caption=caption,
                        parse_mode='Markdown',
                        reply_to_message_id=message.message_id
                    )
                    
        except Exception as e:
            logging.error(f"Error handling item {idx} for Chat {message.chat.id}: {e}")
            bot.send_message(
                message.chat.id,
                f"❌ **Error sending item {idx} of {total_count}:**\n`{str(e)}`",
                parse_mode='Markdown',
                reply_to_message_id=message.message_id
            )
        finally:
            cleanup_file(temp_filename)
            
    # Clean up the progress message when complete
    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        logging.error(f"Failed to delete status message: {e}")

def re_search_url(text):
    """Find the first URL starting with http/https in the text."""
    pattern = r'(https?://[^\s]+)'
    match = re.search(pattern, text)
    return match.group(1) if match else None

def cleanup_file(filepath):
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            logging.info(f"Cleaned up temporary file: {filepath}")
        except Exception as e:
            logging.error(f"Failed to remove file {filepath}: {e}")

def run_health_check_server():
    """Runs a tiny HTTP server on the port requested by the hosting provider to keep deployment healthy."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, format, *args):
            pass  # Suppress logging noise
            
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info(f"Starting health check server on port {port}...")
    server.serve_forever()

if __name__ == "__main__":
    import threading
    # Start health check server in a daemon thread so it runs in parallel to polling
    threading.Thread(target=run_health_check_server, daemon=True).start()
    logging.info("Starting Telegram Bot with Profile Story support...")
    bot.infinity_polling()
