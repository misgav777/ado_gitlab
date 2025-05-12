# ado_gitlab_migration/gitlab_interaction.py
import logging
import time
import requests # For requests.exceptions
import gitlab
from gitlab.exceptions import GitlabHttpError, GitlabCreateError, GitlabGetError
import tempfile # For temporary file handling
import os
import random # For get_or_create_gitlab_label
import re # For sanitizing filenames

logger = logging.getLogger('ado_gitlab_migrator')

# These should ideally be passed from main_migrator or script_config if they vary
# For now, keeping them as module-level constants if they are fixed for the script run
MAX_RETRIES = 3 
RETRY_DELAY_SECONDS = 5 

def call_with_retry(action_description, gitlab_api_call, *args, **kwargs):
    """Wrapper to call GitLab API functions with retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            return gitlab_api_call(*args, **kwargs)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout, GitlabHttpError) as e:
            is_retryable_http_error = isinstance(e, GitlabHttpError) and e.response_code in [429, 500, 502, 503, 504]
            is_timeout_error = isinstance(e, (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout))

            if not (is_retryable_http_error or is_timeout_error):
                logger.error(f"GITLAB API ERROR (non-retryable) during '{action_description}': {e}", exc_info=False)
                raise 
            
            logger.warning(f"Timeout/Retryable Server Error during '{action_description}' (Attempt {attempt + 1}/{MAX_RETRIES}). Error: {e}. Retrying in {RETRY_DELAY_SECONDS * (attempt + 1)}s...")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1)) 
            else:
                logger.error(f"Max retries reached for '{action_description}'. Error: {e}", exc_info=True)
                raise 
        except GitlabCreateError as e_create: 
            # Check for messages indicating the resource already exists or the action is redundant
            if any(msg in str(e_create).lower() for msg in ["has already been taken", "already related", "already assigned", "member already exists"]):
                logger.info(f"INFO during '{action_description}': Item already exists or link/assignment is duplicate. Message: {e_create}")
                return None # Indicate that it's a known "duplicate" like state, not a hard failure
            else:
                logger.error(f"GITLAB CREATE ERROR during '{action_description}': {e_create}", exc_info=True)
                raise # Re-raise other GitlabCreateError exceptions
        except GitlabGetError as e_get: 
            if e_get.response_code == 404:
                logger.debug(f"GitLab GET request for '{action_description}' resulted in 404 (Not Found).")
                raise # Re-raise to be handled by calling code (e.g. label check)
            else: # Other GitlabGetError (not 404)
                logger.error(f"GITLAB GET ERROR during '{action_description}': {e_get}", exc_info=True)
                raise
        except Exception as e: # Catch any other unexpected errors
            logger.error(f"UNEXPECTED ERROR during '{action_description}': {e}", exc_info=True)
            raise # Re-raise other errors

def init_gitlab_connection(gitlab_url, gitlab_pat, gitlab_project_id, script_config):
    """Initializes and returns GitLab connection, project, and group objects."""
    logger.info(f"Connecting to GitLab instance: {gitlab_url}...")
    try:
        # Get client timeout from script_config, default to 60 if not specified
        client_timeout = script_config.get('gitlab_client_timeout', 60)
        gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_pat, timeout=client_timeout)
        gl.auth() # Verify authentication
        project = gl.projects.get(gitlab_project_id)
        
        # Ensure project.namespace is not None before accessing 'id'
        if project.namespace and 'id' in project.namespace:
            group = gl.groups.get(project.namespace['id'])
            logger.info(f"GitLab connection successful. Target GitLab Project: {project.name_with_namespace}, Target Group: {group.full_name}")
            return gl, project, group
        else:
            logger.error(f"GitLab project namespace data is missing or malformed for project ID {gitlab_project_id}.")
            return None, None, None
            
    except gitlab.exceptions.GitlabAuthenticationError as e:
        logger.critical(f"GitLab authentication failed. Check GITLAB_URL and GITLAB_PAT. Error: {e}", exc_info=True)
        return None, None, None
    except Exception as e:
        logger.critical(f"GitLab connection or project/group retrieval failed. Error: {e}", exc_info=True)
        return None, None, None

def get_or_create_gitlab_label(gitlab_project, label_name, script_config, random_module):
    """Gets an existing GitLab label or creates it if it doesn't exist. Returns the label name if successful."""
    if not label_name: 
        logger.debug("Attempted to get/create label with empty name. Skipping.")
        return None
    try:
        # Use call_with_retry for getting the label as well, in case of temporary GitLab issues
        call_with_retry(f"get label '{label_name}'", gitlab_project.labels.get, label_name)
        logger.debug(f"  Label '{label_name}' already exists in GitLab.")
        return label_name
    except GitlabGetError as e_get_label: # Specifically catch GitlabGetError
         if e_get_label.response_code == 404: # Label does not exist
            logger.debug(f"  Label '{label_name}' not found. Attempting to create.")
            try:
                color_strategy = script_config.get('new_label_color_strategy', 'random')
                color = "#C0C0C0" # Default fallback color
                if color_strategy == 'random': 
                    color = "#{:06x}".format(random_module.randint(0, 0xFFFFFF))
                
                call_with_retry(f"create label '{label_name}'", gitlab_project.labels.create, {'name': label_name, 'color': color})
                logger.info(f"  Created GitLab label: {label_name}")
                return label_name
            except Exception as e_create_label_retry: # Catch error from call_with_retry wrapper
                logger.warning(f"  Could not create label '{label_name}' after retries. Error: {e_create_label_retry}. Skipping.")
                return None
         else: # Other GitlabGetError (not 404)
            logger.warning(f"  Error getting label '{label_name}'. Error: {e_get_label}. Skipping.")
            return None
    except Exception as e_label_generic: # Catch any other exception during the get attempt
        logger.warning(f"  An unexpected error occurred with label '{label_name}'. Error: {e_label_generic}. Skipping.")
        return None

def create_gitlab_epic(gitlab_group, payload, ado_item_id):
    """Creates a GitLab epic."""
    action_desc = f"create GitLab epic for ADO #{ado_item_id}"
    try:
        epic = call_with_retry(action_desc, gitlab_group.epics.create, payload)
        if epic: # call_with_retry returns None if it was a duplicate/already exists
            logger.info(f"  SUCCESS: Created GitLab Epic #{epic.iid} for ADO #{ado_item_id}")
        return epic
    except Exception as e: # Catch error from call_with_retry if it re-raises (e.g., max retries exceeded)
        logger.error(f"  Failed to create GitLab epic for ADO #{ado_item_id} after retries or due to non-retryable error. Error: {e}")
        return None


def create_gitlab_issue(gitlab_project, payload, ado_item_id):
    """Creates a GitLab issue."""
    action_desc = f"create GitLab issue for ADO #{ado_item_id}"
    try:
        issue = call_with_retry(action_desc, gitlab_project.issues.create, payload)
        if issue: # call_with_retry returns None if it was a duplicate/already exists
            logger.info(f"  SUCCESS: Created GitLab Issue #{issue.iid} for ADO #{ado_item_id}")
        return issue
    except Exception as e:
        logger.error(f"  Failed to create GitLab issue for ADO #{ado_item_id} after retries or due to non-retryable error. Error: {e}")
        return None

def close_gitlab_issue(gitlab_project, issue_iid):
    """Closes a GitLab issue."""
    action_desc = f"close GitLab issue #{issue_iid}"
    try:
        issue_to_close = call_with_retry(f"fetch issue {issue_iid} for closing", gitlab_project.issues.get, issue_iid)
        if issue_to_close: # Ensure issue was fetched
            issue_to_close.state_event = 'close'
            call_with_retry(action_desc, issue_to_close.save) # This call might also need retry for robustness
            logger.info(f"    SUCCESS: Closed GitLab Issue #{issue_iid}")
            return True
        return False # Issue not fetched
    except Exception as e:
        logger.warning(f"    Could not close GitLab Issue #{issue_iid}. Error: {e}")
        return False

def add_gitlab_note(gitlab_item, note_payload, ado_comment_id, item_type, item_iid):
    """Adds a note (comment) to a GitLab item (issue or epic)."""
    action_desc = f"add ADO comment {ado_comment_id} to GL {item_type} #{item_iid}"
    try:
        # call_with_retry will handle retries and "already exists" if the API signals it
        call_with_retry(action_desc, gitlab_item.notes.create, note_payload)
        logger.debug(f"    Successfully added or confirmed existing ADO comment (original ID: {ado_comment_id})")
        return True
    except Exception as e: # call_with_retry might re-raise if all retries fail for non-duplicate errors
        logger.warning(f"    Error adding ADO comment ID {ado_comment_id} to GitLab {item_type} #{item_iid} after retries. Error: {e}", exc_info=True)
        return False

def link_gitlab_epic_issue(gitlab_group, epic_iid, issue_global_id):
    """Links a GitLab issue to a GitLab epic."""
    action_desc = f"link GL Issue (global_id {issue_global_id}) to GL Epic #{epic_iid}"
    try:
        retrieved_epic = call_with_retry(f"fetch epic {epic_iid} for linking", gitlab_group.epics.get, epic_iid)
        if retrieved_epic:
            # The call_with_retry will handle GitlabCreateError if it's a duplicate ("already assigned")
            # and return None, which we interpret as "idempotently successful".
            if call_with_retry(action_desc, retrieved_epic.add_issue, issue_global_id) is not None: # None means it was a duplicate
                 logger.info(f"      SUCCESS: {action_desc}")
            # If call_with_retry returned None, it means it was a duplicate, which is fine for idempotency.
            return True 
        return False # Epic not retrieved
    except Exception as e:
        logger.warning(f"      Error during: {action_desc}. Error: {e}", exc_info=True)
        return False

def link_gitlab_issues(gitlab_project, source_issue_iid, target_issue_iid, link_type):
    """Creates a link between two GitLab issues."""
    action_desc = f"link GL Issue #{source_issue_iid} to #{target_issue_iid} as {link_type}"
    try:
        source_issue_gl = call_with_retry(f"fetch source issue {source_issue_iid} for linking", gitlab_project.issues.get, source_issue_iid)
        if source_issue_gl:
            link_payload = {'target_project_id': gitlab_project.id, 'target_issue_iid': target_issue_iid, 'link_type': link_type}
            # call_with_retry handles duplicate link errors and returns None in that case.
            if call_with_retry(action_desc, source_issue_gl.links.create, link_payload) is not None: # None means it was a duplicate
                logger.info(f"      SUCCESS: {action_desc}")
            return True 
        return False # Source issue not retrieved
    except Exception as e:
        logger.warning(f"      Error during: {action_desc}. Error: {e}", exc_info=True)
        return False

# --- THIS IS THE FUNCTION THAT WAS MISSING/INCORRECTLY CALLED ---
def upload_image_and_get_markdown(gitlab_project, filename_suggestion, image_bytes):
    """
    Uploads image data to GitLab project and returns the Markdown link.
    Manages a temporary file for the upload.
    """
    if not image_bytes:
        logger.warning("    upload_image_and_get_markdown called with no image_bytes.")
        return None
    
    # Sanitize filename suggestion for safety
    # Remove path components, keep only filename
    base_filename = os.path.basename(filename_suggestion)
    # Replace characters not typically allowed or problematic in web contexts/filenames
    safe_filename = re.sub(r'[^\w\.\-]', '_', base_filename)
    if not safe_filename: # Fallback if sanitization results in empty string
        safe_filename = f"migrated_image_{int(time.time())}.png" # Or derive extension from content-type if available

    tmp_file_path = None # Initialize to ensure it's defined in finally block
    try:
        # Create a temporary file to hold the image data
        # Suffix helps GitLab determine file type if filename is generic
        _, ext = os.path.splitext(safe_filename)
        if not ext: # If no extension after sanitization, default to .png
            ext = ".png" 
            #safe_filename += ext # Filename for upload doesn't strictly need it if tmp file has it

        # Use NamedTemporaryFile correctly by getting its name and writing to it, then using the path
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix="migrated_ado_img_") as tmp_file:
            tmp_file.write(image_bytes)
            tmp_file_path = tmp_file.name # Get path while file is open and valid
        # File is closed here, but still exists due to delete=False

        logger.debug(f"    Uploading image '{safe_filename}' from temporary file {tmp_file_path} to GitLab project...")
        
        action_description = f"upload image {safe_filename}"
        
        # The python-gitlab library's project.upload() expects a file object opened in 'rb' or filepath
        # We pass the filepath of the closed temporary file.
        # The `filename` parameter to `project.upload` is what GitLab will name the file.
        upload_result = call_with_retry(
            action_description,
            gitlab_project.upload, 
            filepath=tmp_file_path,  
            filename=safe_filename 
        )

        if upload_result and isinstance(upload_result, dict) and 'markdown' in upload_result:
            logger.info(f"    Image '{safe_filename}' uploaded successfully. Markdown: {upload_result['markdown']}")
            return upload_result['markdown']
        else:
            logger.warning(f"    GitLab upload for '{safe_filename}' did not return expected Markdown. Result: {upload_result}")
            return None

    except Exception as e:
        logger.error(f"    Failed to upload image '{safe_filename}' to GitLab. Error: {e}", exc_info=True)
        return None
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.unlink(tmp_file_path) 
                logger.debug(f"    Temporary image file {tmp_file_path} deleted.")
            except Exception as e_del:
                logger.warning(f"    Could not delete temporary image file {tmp_file_path}. Error: {e_del}")
