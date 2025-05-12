# ado_gitlab_migration/main_migrator.py
import logging
import sys
import random # For label colors if not defined
from datetime import datetime, timezone
import re # For link URL parsing & project name sanitization
import os # For path operations

# --- Configuration (User-provided, imported from config.py) ---
try:
    from config import AZURE_ORG_URL, AZURE_PROJECT, AZURE_PAT, GITLAB_URL, GITLAB_PAT, GITLAB_PROJECT_ID
except ImportError:
    # This print is a fallback for when the logger isn't yet configured.
    print("CRITICAL: config.py not found or missing required variables. Please create it with your credentials and project details.")
    sys.exit(1)

# --- Project Modules ---
# These imports assume the files are in the same directory or Python path is set.
import config_loader
import ado_client
import gitlab_interaction 
import utils

# --- Dynamic Filename Generation ---
# Sanitize AZURE_PROJECT name for use in filenames (replace spaces, special chars)
safe_project_name = re.sub(r'[^\w\-_\.]', '_', AZURE_PROJECT) if AZURE_PROJECT else "default_project"
LOG_FILE = f"{safe_project_name}_migration_log.txt"
ADO_GITLAB_MAP_FILE = f"{safe_project_name}_ado_gitlab_map.json"


# --- Logging Setup ---
logger = logging.getLogger('ado_gitlab_migrator')
logger.setLevel(logging.DEBUG) # Capture all levels of logs (DEBUG, INFO, WARNING, ERROR, CRITICAL)

# Prevent duplicate handlers if script is re-imported or run in certain environments
if not logger.handlers:
    # File Handler - for persistent logs
    try:
        # Use the dynamically generated LOG_FILE name
        file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8') # Append mode
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.INFO) # Log INFO and above to file by default
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"CRITICAL: Failed to configure file logger for {LOG_FILE}: {e}. File logging will be unavailable.")

    # Console Handler - for immediate feedback
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(levelname)s - %(message)s') # Simpler format for console
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO) # Show INFO and above on console
    logger.addHandler(console_handler)

# --- Silence overly verbose logs from underlying libraries ---
logging.getLogger("gitlab").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("msrest").setLevel(logging.INFO)


# --- Main Orchestration ---
def main():
    logger.info("--- Starting ADO to GitLab Migration Script ---")
    logger.info(f"Using ADO Project: {AZURE_PROJECT}")
    logger.info(f"Log file: {os.path.abspath(LOG_FILE)}") # Log absolute path for clarity
    logger.info(f"Mapping file: {os.path.abspath(ADO_GITLAB_MAP_FILE)}") # Log absolute path
    logger.info(f"Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # MIGRATION_CONFIG_FILE is global in config_loader or can be passed if needed
    script_config = config_loader.load_migration_config() 
    if script_config is None:
        logger.critical("Exiting due to configuration loading failure.")
        sys.exit(1)

    # Initialize Azure DevOps connection
    _, ado_wit_client, ado_core_client = ado_client.init_ado_connection(AZURE_ORG_URL, AZURE_PAT)
    if not ado_wit_client or not ado_core_client:
        # init_ado_connection already logs critical error
        sys.exit(1)
    
    try: # Verify ADO project after successful connection
        ado_project_details = ado_core_client.get_project(AZURE_PROJECT)
        logger.info(f"Azure DevOps Target Project Verified: {ado_project_details.name} (ID: {ado_project_details.id})")
    except Exception as e:
        logger.critical(f"Failed to verify ADO Project '{AZURE_PROJECT}'. Error: {e}", exc_info=True)
        sys.exit(1)

    # Initialize GitLab connection
    gl, gitlab_project, gitlab_group = gitlab_interaction.init_gitlab_connection(
        GITLAB_URL, GITLAB_PAT, GITLAB_PROJECT_ID, script_config
    )
    if not gl or not gitlab_project or not gitlab_group:
        # init_gitlab_connection already logs critical error
        sys.exit(1)

    # Load existing ADO ID to GitLab ID mapping, passing the dynamic filepath
    ado_id_to_gitlab = config_loader.load_mapping(filepath=ADO_GITLAB_MAP_FILE)
    logger.info(f"Loaded {len(ado_id_to_gitlab)} existing ADO-GitLab mappings from {ADO_GITLAB_MAP_FILE}.")

    # --- Determine fields to select for ADO query ---
    ado_priority_field_ref = script_config.get('ado_priority_field_ref_name')
    # Start with base fields absolutely required by the script
    fields_to_select_list = ["[System.Id]", "[System.Title]", "[System.WorkItemType]", "[System.State]"]
    
    # Add configured description fields from migration_config.yaml
    # Default to ["System.Description"] if not specified or empty
    ado_desc_fields_config = script_config.get('ado_description_fields', ["System.Description"])
    if not ado_desc_fields_config: # Ensure it's not empty, fallback if it is
        ado_desc_fields_config = ["System.Description"]
        
    for field_ref in ado_desc_fields_config:
        if field_ref and f"[{field_ref}]" not in fields_to_select_list: # Check if field_ref is not None/empty
            fields_to_select_list.append(f"[{field_ref}]")
            
    # Add priority field if configured
    if ado_priority_field_ref and f"[{ado_priority_field_ref}]" not in fields_to_select_list:
        fields_to_select_list.append(f"[{ado_priority_field_ref}]")
    
    ado_work_item_refs = ado_client.query_ado_work_item_refs(ado_wit_client, AZURE_PROJECT, fields_to_select_list)
    if not ado_work_item_refs: 
        logger.info("No work items to process based on ADO query.")
        # Script will proceed to linking phase if map has items from previous runs.
        
    # --- Phase 1: Create Epics and Issues (and migrating comments) ---
    logger.info("--- Phase 1: Creating Epics and Issues (and migrating comments) ---")
    for wi_ref in ado_work_item_refs:
        ado_work_item_id = wi_ref.id
        logger.info(f"Processing ADO Work Item #{ado_work_item_id}...")
        
        gitlab_item_for_comments = None
        gitlab_item_type_for_comments = None # Will be 'epic' or 'issue'

        if ado_work_item_id in ado_id_to_gitlab:
            existing_mapping = ado_id_to_gitlab[ado_work_item_id]
            logger.info(f"ADO #{ado_work_item_id} already mapped to GitLab {existing_mapping['type']} #{existing_mapping['id']}. Will not re-create item.")
            try:
                gitlab_item_type_for_comments = existing_mapping['type']
                if gitlab_item_type_for_comments == "epic":
                    gitlab_item_for_comments = gitlab_interaction.call_with_retry(
                        f"fetch existing epic {existing_mapping['id']}", gitlab_group.epics.get, existing_mapping['id']
                    )
                else: # issue
                    gitlab_item_for_comments = gitlab_interaction.call_with_retry(
                        f"fetch existing issue {existing_mapping['id']}", gitlab_project.issues.get, existing_mapping['id']
                    )
            except Exception as e_fetch_existing:
                logger.error(f"Failed to fetch existing GitLab {gitlab_item_type_for_comments or 'item'} #{existing_mapping.get('id')} for ADO #{ado_work_item_id}. Comment/Link migration might be skipped for this item. Error: {e_fetch_existing}")
                gitlab_item_for_comments = None # Ensure it's None so comment migration is skipped if fetch fails
        else: # Item not in map, needs to be created
            try:
                ado_work_item_details = ado_client.get_ado_work_item_details(ado_wit_client, ado_work_item_id)
                if not ado_work_item_details: 
                    logger.error(f"Could not retrieve details for ADO item #{ado_work_item_id}. Skipping this item.")
                    continue

                title = ado_work_item_details.fields.get("System.Title", f"Untitled ADO Item {ado_work_item_id}")
                
                # --- Construct main description from configured fields ---
                concatenated_description_html = ""
                first_desc_field = True
                for field_ref_name in ado_desc_fields_config: # Use the list from config
                    field_html_content = ado_work_item_details.fields.get(field_ref_name, "")
                    if field_html_content and isinstance(field_html_content, str): # Ensure it's a string and has content
                        if not first_desc_field and concatenated_description_html: # Add separator if not the first and previous had content
                            concatenated_description_html += "\n<hr/>\n" 
                        
                        # Optionally add field name as a header (can be configured)
                        # field_friendly_name = field_ref_name.split('.')[-1] 
                        # concatenated_description_html += f"<h3>{field_friendly_name.replace('ReproSteps', 'Reproduction Steps')}</h3>\n"
                        
                        concatenated_description_html += field_html_content
                        first_desc_field = False if concatenated_description_html.strip() else True # Update based on actual content added
                
                if script_config.get('migrate_comment_images', False): # Use same flag for description images
                    logger.debug(f"  Attempting to migrate images in main description for ADO #{ado_work_item_id}")
                    concatenated_description_html = utils.migrate_images_in_html_text(
                        concatenated_description_html, gitlab_project, AZURE_PAT, script_config, gitlab_interaction
                    )
                description_md = utils.basic_html_to_markdown(concatenated_description_html)
                # --- End main description construction ---

                ado_type = ado_work_item_details.fields.get("System.WorkItemType", "WorkItem")
                ado_state = ado_work_item_details.fields.get("System.State", "Undefined")
                ado_priority_val = ado_work_item_details.fields.get(ado_priority_field_ref) if ado_priority_field_ref else None
                
                # Append migration footer to the already processed Markdown description
                migration_footer = f"\n\n---\nMigrated from ADO #{ado_work_item_id} (Type: {ado_type}, State: {ado_state}"
                if ado_priority_val is not None: migration_footer += f", Priority: {ado_priority_val}"
                migration_footer += ")"
                final_description_for_gitlab = description_md + migration_footer

                labels_to_apply_names = []
                gitlab_target_type_str = script_config.get('ado_to_gitlab_type', {}).get(ado_type, script_config.get('default_gitlab_type', 'issue'))
                gitlab_item_type_for_comments = gitlab_target_type_str # For consistency in comment phase

                state_mapping_config = script_config.get('ado_state_to_gitlab_labels', {}).get(ado_state)
                action_close_issue = False
                if state_mapping_config and isinstance(state_mapping_config, dict):
                    labels_to_apply_names.extend(state_mapping_config.get('labels', []))
                    if state_mapping_config.get('action') == '_close_issue_': action_close_issue = True
                else:
                    prefix = script_config.get('unmapped_ado_state_label_prefix', 'ado_state::')
                    if ado_state and ado_state != "Undefined": labels_to_apply_names.append(f"{prefix}{ado_state}")
                
                if ado_priority_val is not None and script_config.get('ado_priority_to_gitlab_label'):
                    priority_label = script_config['ado_priority_to_gitlab_label'].get(ado_priority_val)
                    if priority_label: labels_to_apply_names.append(priority_label)
                    else: labels_to_apply_names.append(f"{script_config.get('unmapped_ado_priority_label_prefix', 'ado_priority::')}{ado_priority_val}")
                
                if gitlab_target_type_str != 'epic' and ado_type: labels_to_apply_names.append(f"ado_type::{ado_type}")
                
                final_gl_labels = []
                for label_name in list(set(labels_to_apply_names)): 
                    if not label_name: continue # Skip empty label names
                    created_label_name = gitlab_interaction.get_or_create_gitlab_label(gitlab_project, label_name, script_config, random)
                    if created_label_name:
                        final_gl_labels.append(created_label_name)
                
                item_payload = {'title': title, 'description': final_description_for_gitlab, 'labels': final_gl_labels}
                created_gl_item = None
                if gitlab_target_type_str == "epic":
                    created_gl_item = gitlab_interaction.create_gitlab_epic(gitlab_group, item_payload, ado_work_item_id)
                else: # issue
                    created_gl_item = gitlab_interaction.create_gitlab_issue(gitlab_project, item_payload, ado_work_item_id)
                
                if created_gl_item: 
                    if gitlab_target_type_str == "issue" and action_close_issue:
                        gitlab_interaction.close_gitlab_issue(gitlab_project, created_gl_item.iid)
                    gitlab_item_for_comments = created_gl_item # Set for comment migration
                    ado_id_to_gitlab[ado_work_item_id] = {'type': gitlab_target_type_str, 'id': created_gl_item.iid, 'gitlab_global_id': created_gl_item.id}
                    config_loader.save_mapping(ado_id_to_gitlab, filepath=ADO_GITLAB_MAP_FILE) # Pass dynamic filepath
                else: 
                    logger.error(f"  Failed to create GitLab {gitlab_target_type_str} for ADO #{ado_work_item_id}. Skipping further processing for this item.")
                    continue # Skip to next ADO item if creation failed
            except Exception as e_general_create:
                logger.error(f"  UNEXPECTED ERROR during item creation phase for ADO #{ado_work_item_id}.", exc_info=True)
                continue # Skip to next ADO item

        # --- Migrate Comments (with images) ---
        if script_config.get('migrate_comments', False) and gitlab_item_for_comments:
            logger.info(f"  Fetching comments for ADO #{ado_work_item_id} (GitLab {gitlab_item_type_for_comments} #{gitlab_item_for_comments.iid})...")
            ado_comments_list = ado_client.get_ado_work_item_comments(ado_wit_client, AZURE_PROJECT, ado_work_item_id)
            if ado_comments_list:
                logger.info(f"  Found {len(ado_comments_list)} comments in ADO. Migrating...")
                for ado_comment in ado_comments_list: # Already sorted by client
                    try:
                        comment_text_html = ado_comment.text
                        if script_config.get('migrate_comment_images', False): # Check flag for images in comments
                            logger.debug(f"    Attempting to migrate images in comment ID {ado_comment.id} for ADO #{ado_work_item_id}")
                            comment_text_html = utils.migrate_images_in_html_text(
                                comment_text_html, gitlab_project, AZURE_PAT, script_config, gitlab_interaction
                            )
                        comment_text_md = utils.basic_html_to_markdown(comment_text_html)

                        author_identity = ado_comment.created_by
                        author_repr = utils.get_ado_user_representation(author_identity, script_config)
                        ts_dt = ado_comment.created_date
                        if ts_dt.tzinfo is None: ts_dt_utc = ts_dt.replace(tzinfo=timezone.utc)
                        else: ts_dt_utc = ts_dt.astimezone(timezone.utc)
                        ts_str = ts_dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
                        header_format = script_config.get('migrated_comment_header_format', "**Comment from ADO by {author} on {timestamp}:**\n\n")
                        header = header_format.format(author=author_repr, timestamp=ts_str)
                        note_body = f"{header}{comment_text_md}"
                        payload = {'body': note_body}
                        try: payload['created_at'] = ts_dt_utc.isoformat()
                        except: pass # Silently ignore if ISO formatting fails, GitLab will use current time
                        
                        gitlab_interaction.add_gitlab_note(gitlab_item_for_comments, payload, ado_comment.id, gitlab_item_type_for_comments, gitlab_item_for_comments.iid)
                    except Exception as e_comm_indiv: 
                        logger.warning(f"    Error processing individual ADO comment ID {ado_comment.id if ado_comment else 'N/A'}. Error: {e_comm_indiv}", exc_info=True)
            else:
                logger.info(f"  No comments found in ADO for #{ado_work_item_id} to migrate.")
        
    # --- Phase 2: Link Parent/Child and Other Relations ---
    logger.info("--- Phase 2: Linking Parent/Child and Other Relations ---")
    if not ado_work_item_refs: logger.info("No work items to process for linking (based on initial query).")
    else:
        for wi_ref_source in ado_work_item_refs:
            source_ado_id = wi_ref_source.id
            if source_ado_id not in ado_id_to_gitlab: continue # Source item wasn't migrated
            
            source_gitlab_info = ado_id_to_gitlab[source_ado_id]
            logger.info(f"Processing links for source ADO #{source_ado_id} (GitLab {source_gitlab_info['type']} #{source_gitlab_info['id']})...")
            
            ado_item_with_relations = ado_client.get_ado_work_item_details(ado_wit_client, source_ado_id, expand_relations=True)
            if not ado_item_with_relations:
                logger.warning(f"  Could not get relations for ADO source #{source_ado_id}. Skipping link processing for this item.")
                continue
            
            relations = getattr(ado_item_with_relations, "relations", None)
            if relations:
                for rel in relations:
                    target_ado_id = -1 # Default for logging if parsing fails
                    try:
                        rel_url_str = getattr(rel, 'url', "")
                        if not rel_url_str:
                            logger.debug(f"  Skipping relation with empty URL for source ADO #{source_ado_id}")
                            continue
                        
                        # Regex to specifically match ADO work item API URLs and extract the ID
                        work_item_url_pattern = r"https?://[^/]+(?:/[^/]+)?/[^/]+/_apis/wit/workitems/(\d+)"
                        match = re.search(work_item_url_pattern, rel_url_str, re.IGNORECASE)

                        if not match:
                            logger.debug(f"  Skipping non-standard work item relation URL: '{rel_url_str}' for source ADO #{source_ado_id}")
                            continue
                        target_ado_id_str = match.group(1) # The captured digits
                        target_ado_id = int(target_ado_id_str)
                        
                        ado_link_ref_name = rel.rel 
                        ado_link_friendly_name = getattr(rel, 'attributes', {}).get('name', 'UnknownLinkType')
                        logger.debug(f"  Found ADO link: Source ADO #{source_ado_id} --[{ado_link_friendly_name} ({ado_link_ref_name})]--> Target ADO #{target_ado_id}")
                        
                        if target_ado_id not in ado_id_to_gitlab:
                            logger.info(f"    Target ADO #{target_ado_id} for link from ADO #{source_ado_id} was not mapped. Skipping.")
                            continue
                        target_gitlab_info = ado_id_to_gitlab[target_ado_id]
                        
                        is_hierarchical, parent_gl, child_gl = False, None, None
                        if ado_link_ref_name == "System.LinkTypes.Hierarchy-Forward": # Source is Child, Target is Parent
                            parent_gl, child_gl, is_hierarchical = target_gitlab_info, source_gitlab_info, True
                        elif ado_link_ref_name == "System.LinkTypes.Hierarchy-Reverse": # Source is Parent, Target is Child
                            parent_gl, child_gl, is_hierarchical = source_gitlab_info, target_gitlab_info, True
                        
                        if is_hierarchical:
                            if parent_gl['type'] == 'epic' and child_gl['type'] == 'issue':
                                gitlab_interaction.link_gitlab_epic_issue(gitlab_group, parent_gl['id'], child_gl['gitlab_global_id'])
                            elif parent_gl['type'] == 'issue' and child_gl['type'] == 'issue':
                                gitlab_interaction.link_gitlab_issues(gitlab_project, parent_gl['id'], child_gl['id'], 'relates_to')
                            continue # Processed as hierarchical, move to next relation
                        
                        # Handle Generic Links based on Configuration
                        mapped_gl_link_type = script_config.get('ado_to_gitlab_link_type_mapping', {}).get(ado_link_ref_name)
                        if not mapped_gl_link_type: # If not explicitly mapped, check for a default
                            mapped_gl_link_type = script_config.get('default_gitlab_link_type') # This might be null/None

                        if mapped_gl_link_type and mapped_gl_link_type not in ["_parent_of_current_", "_child_of_current_"]: # Ensure it's a valid GitLab link type
                            if source_gitlab_info['type'] == 'issue' and target_gitlab_info['type'] == 'issue':
                                gitlab_interaction.link_gitlab_issues(gitlab_project, source_gitlab_info['id'], target_gitlab_info['id'], mapped_gl_link_type)
                            else: 
                                logger.info(f"    Skipping generic link type '{mapped_gl_link_type}': Both source and target ADO items must be mapped to GitLab 'issues' to create this link type.")
                        # Check if the link type was explicitly set to null (ignore) or just wasn't in the map
                        elif ado_link_ref_name not in script_config.get('ado_to_gitlab_link_type_mapping', {}):
                             # Log only if it wasn't explicitly set to null in the mapping
                            if script_config.get('ado_to_gitlab_link_type_mapping', {}).get(ado_link_ref_name) is not None:
                                logger.info(f"    ADO Link type '{ado_link_ref_name}' ({ado_link_friendly_name}) from ADO #{source_ado_id} to #{target_ado_id} is not mapped and no default applicable. Skipping.")
                        # else: link type was explicitly set to null or was a special keyword already handled.
                            
                    except Exception as e_rel_proc: 
                        logger.warning(f"    Error processing relation for ADO source {source_ado_id} to target {target_ado_id}: {getattr(rel, 'url', 'N/A')}. Error: {e_rel_proc}", exc_info=True)
            else: 
                logger.debug(f"  No relations found for ADO source #{source_ado_id}.")

    logger.info("--- Migration Script Finished ---")

if __name__ == '__main__':
    main()
