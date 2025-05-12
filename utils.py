# ado_gitlab_migration/utils.py
import re
import logging
import requests 
import os
from urllib.parse import urlparse, unquote
import base64 
import time 
import random # Added for filename fallback if not already present

logger = logging.getLogger('ado_gitlab_migrator')

def get_ado_user_representation(ado_user_identity, config_data):
    if not ado_user_identity: return "Unknown ADO User"
    display_name = getattr(ado_user_identity, 'display_name', 'Unknown Name')
    unique_name = getattr(ado_user_identity, 'unique_name', None) or \
                  getattr(ado_user_identity, 'name', None) 
    user_map = config_data.get('user_mapping', {})
    mapped_gitlab_user = None
    if unique_name and unique_name in user_map:
        mapped_gitlab_user = user_map[unique_name]
    elif display_name in user_map: 
        mapped_gitlab_user = user_map[display_name]

    if mapped_gitlab_user:
        return f"GitLab user '{mapped_gitlab_user}' (ADO: {display_name})"
    default_gitlab_user = user_map.get("_default_")
    if default_gitlab_user:
        return f"'{default_gitlab_user}' (Original ADO user: {display_name})"
    user_details = f"ADO user: {display_name}"
    if unique_name and unique_name.lower() != display_name.lower(): 
        user_details += f" [{unique_name}]"
    return user_details

def basic_html_to_markdown(html_content):
    """
    More robust (but still basic) HTML to Markdown conversion.
    Tries to handle common tags better. For very complex HTML, a dedicated
    library like html2text, pandoc (via pypandoc), or markdownify is recommended.
    """
    if not html_content:
        return ""
    
    text = str(html_content)

    # Pre-processing: Normalize whitespace and handle self-closing tags simply
    text = re.sub(r'\s+', ' ', text) # Normalize multiple spaces to one
    text = text.replace("<br />", "<br>").replace("<br/>", "<br>")

    # Block-level elements that introduce newlines
    # Paragraphs - ensure double newline after
    text = re.sub(r'<p[^>]*>', '', text, flags=re.IGNORECASE) 
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE) 
    
    # Line breaks
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

    # Headings
    for i in range(6, 0, -1): # H6 down to H1
        text = re.sub(r'<h{i}[^>]*>(.*?)</h{i}>'.format(i=i), ('#' * i) + r' \1\n\n', text, flags=re.IGNORECASE | re.DOTALL)

    # Lists (more careful handling)
    # Unordered lists
    text = re.sub(r'<ul[^>]*>', '\n', text, flags=re.IGNORECASE) # Add newline before list
    text = re.sub(r'</ul[^>]*>', '\n', text, flags=re.IGNORECASE) # Add newline after list
    # Ordered lists
    text = re.sub(r'<ol[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</ol[^>]*>', '\n', text, flags=re.IGNORECASE)
    # List items - this is tricky with nested lists without a full parser
    # This basic version will just prepend '*' or '1.'
    # For ordered lists, it won't re-number correctly if source HTML is complex.
    text = re.sub(r'<li[^>]*>(.*?)</li>', r'\n* \1', text, flags=re.IGNORECASE | re.DOTALL) # Basic unordered
    # A more complex approach would be needed for proper ordered list numbering.

    # Blockquotes
    text = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'\n> \1\n', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Horizontal rules
    text = re.sub(r'<hr[^>]*>', '\n---\n', text, flags=re.IGNORECASE)

    # Preformatted text and Code blocks
    # This will convert <pre><code>...</code></pre> or just <pre>...</pre>
    # It doesn't determine language for ```lang
    text = re.sub(r'<pre[^>]*><code[^>]*>(.*?)</code></pre>', r'\n```\n\1\n```\n\n', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n\n', text, flags=re.IGNORECASE | re.DOTALL)
    # Inline code
    text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.IGNORECASE | re.DOTALL)


    # Inline styling (bold, italic, underline - basic)
    text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<b>(.*?)</b>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<em>(.*?)</em>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<i>(.*?)</i>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<u>(.*?)</u>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL) # Markdown doesn't have underline, using italics

    # Links (ensure this runs after image migration if images are wrapped in links)
    try:
        text = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.IGNORECASE | re.DOTALL)
    except Exception: 
        logger.debug("Regex for link conversion failed in basic_html_to_markdown.")
        
    # Table conversion (VERY basic, structure might be lost for complex tables)
    # This is a placeholder and would need significant improvement for real tables.
    # For now, it might just strip table tags or make a mess.
    # A proper library is essential for good table conversion.
    text = re.sub(r'<table[^>]*>', '\n| Table Header 1 | Table Header 2 |\n|---|---|\n', text, flags=re.IGNORECASE) # Placeholder
    text = re.sub(r'</table[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<tr[^>]*>', '| ', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr[^>]*>', ' |\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<td[^>]*>(.*?)</td>', r'\1 | ', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<th[^>]*>(.*?)</th>', r'\1 | ', text, flags=re.IGNORECASE | re.DOTALL)


    # Strip any remaining HTML tags as a last resort
    text = re.sub(r'<[^>]+>', '', text) 
    
    # Clean up excessive newlines and leading/trailing whitespace on lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(filter(None, lines)) # Remove empty lines that might result
    text = re.sub(r'\n{3,}', '\n\n', text) # Reduce 3+ newlines to 2

    return text.strip()


def download_ado_image(image_url, ado_pat_raw_token, script_config):
    timeout = script_config.get('ado_image_download_timeout', 30)
    max_size = script_config.get('max_image_size_bytes', 10 * 1024 * 1024) 
    auth_string = f":{ado_pat_raw_token}"
    encoded_auth_string = base64.b64encode(auth_string.encode('utf-8')).decode('ascii')
    headers = {'Authorization': f'Basic {encoded_auth_string}', 'Accept': 'application/octet-stream'}
    
    try:
        logger.debug(f"Attempting to download image from ADO: {image_url} with Basic Auth.")
        response = requests.get(image_url, headers=headers, stream=True, timeout=timeout, allow_redirects=True)
        logger.debug(f"ADO Image download response status: {response.status_code}")
        if 'content-type' in response.headers: logger.debug(f"ADO Image download response Content-Type: {response.headers['content-type']}")
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' in content_type:
            logger.warning(f"Downloaded content from {image_url} appears to be HTML. Content-Type: {content_type}")
            try: logger.debug(f"HTML snippet: {response.text[:200] if response.content else 'No content'}")
            except: pass
            return None, None
        content_length = response.headers.get('Content-Length')
        if content_length and int(content_length) > max_size:
            logger.warning(f"Image at {image_url} too large ({content_length} bytes > {max_size} bytes). Skipping.")
            return None, None
        image_bytes = response.content 
        if not image_bytes:
            logger.warning(f"Image at {image_url} downloaded 0 bytes. Skipping.")
            return None, None
        if len(image_bytes) > max_size: 
            logger.warning(f"Image at {image_url} too large after download ({len(image_bytes)} bytes > {max_size} bytes). Skipping.")
            return None, None
        filename = None
        if 'content-disposition' in response.headers:
            cd = response.headers['content-disposition']
            fname_match = re.search(r'filename\*?=(?:UTF-\d\'\')?([^;\s]+)', cd, flags=re.IGNORECASE)
            if fname_match: filename = unquote(fname_match.group(1).strip('"\'')) # unquote filename
        if not filename:
            try:
                parsed_url_path = unquote(urlparse(image_url).path) # Unquote path before basename
                filename = os.path.basename(parsed_url_path)
                if not filename or '.' not in filename: 
                    ext_map = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif', 'image/bmp': '.bmp', 'image/webp': '.webp'}
                    file_ext = ext_map.get(content_type, '.png') 
                    filename = f"migrated_image_{int(time.time())}_{random.randint(100,999)}{file_ext}"
            except Exception: filename = f"migrated_image_{int(time.time())}_{random.randint(100,999)}.png" 
        logger.info(f"Successfully downloaded image from {image_url} as {filename} ({len(image_bytes)} bytes). Content-Type: {content_type}")
        return filename, image_bytes
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error downloading image {image_url}. Status: {http_err.response.status_code}. Response: {http_err.response.text[:200]}")
        return None, None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download image {image_url}. Error: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error downloading image {image_url}. Error: {e}", exc_info=True)
        return None, None

def migrate_images_in_html_text(html_content, gitlab_project_obj, ado_pat_raw_token, script_config, gitlab_interaction_module):
    if not html_content or not script_config.get('migrate_comment_images', False) : 
        return html_content 
    img_pattern = re.compile(r'<img\s+(?:[^>]*?\s+)?src\s*=\s*["\']([^"\']+)["\'][^>]*>', re.IGNORECASE | re.DOTALL)
    matches = list(img_pattern.finditer(html_content))
    if not matches: return html_content 
    logger.debug(f"Found {len(matches)} potential image tags in HTML content to process.")
    modified_html = html_content
    for match in reversed(matches):
        img_tag_full = match.group(0)  
        ado_image_url = match.group(1) 
        if "gitlab" in ado_image_url.lower() and "/uploads/" in ado_image_url.lower():
            logger.debug(f"    Skipping already migrated GitLab image URL: {ado_image_url}")
            continue
        if not ado_image_url.lower().startswith(("http:", "https:")):
            logger.debug(f"    Skipping non-HTTP(S) image URL: {ado_image_url}")
            continue
        logger.info(f"  Processing image URL from HTML: {ado_image_url}")
        original_filename, image_bytes = download_ado_image(ado_image_url, ado_pat_raw_token, script_config)
        replacement_text = script_config.get('failed_image_placeholder', "[Image: {url} - Migration Failed]").format(url=ado_image_url)
        if image_bytes and original_filename:
            try:
                markdown_link = gitlab_interaction_module.upload_image_and_get_markdown(
                    gitlab_project_obj, original_filename, image_bytes
                )
                if markdown_link:
                    logger.info(f"    Successfully migrated image {ado_image_url} to GitLab: {markdown_link}")
                    replacement_text = markdown_link
                else: logger.warning(f"    Failed to upload image {ado_image_url} to GitLab or get Markdown link.")
            except Exception as e_upload:
                logger.error(f"    Error during GitLab upload for image {ado_image_url}: {e_upload}", exc_info=True)
        else: logger.warning(f"    Failed to download image from ADO: {ado_image_url}. Using placeholder.")
        modified_html = modified_html[:match.start()] + replacement_text + modified_html[match.end():]
    return modified_html
