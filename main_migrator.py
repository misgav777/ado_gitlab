# ado_gitlab_migration/main_migrator.py
import logging
import sys
import random
from datetime import datetime, timezone, date
import re
import os
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor, as_completed
import json


try:
    from config import AZURE_ORG_URL, AZURE_PROJECT, AZURE_PAT, GITLAB_URL, GITLAB_PAT, GITLAB_PROJECT_ID
except ImportError:
    print("CRITICAL: config.py not found or missing required variables. Please create it.")
    sys.exit(1)

import config_loader
import ado_client
import gitlab_interaction
import utils

safe_project_name = re.sub(r'[^\w\-_\.]', '_', AZURE_PROJECT) if AZURE_PROJECT else "default_project"
LOG_FILE = f"{safe_project_name}_migration_log.txt"
ADO_GITLAB_MAP_FILE = f"{safe_project_name}_ado_gitlab_map.json"

logger = logging.getLogger('ado_gitlab_migrator')
logger.setLevel(logging.DEBUG) # Set to DEBUG for detailed output during development
if not logger.handlers:
    try:
        file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.INFO) # Or DEBUG
        logger.addHandler(file_handler)
    except Exception as e: print(f"CRITICAL: Failed to configure file logger for {LOG_FILE}: {e}.")
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO) # Or DEBUG
    logger.addHandler(console_handler)

logging.getLogger("gitlab").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("msrest").setLevel(logging.INFO)

def save_checkpoint(completed_ids, total_count):
    checkpoint = {
        'completed_ids': completed_ids,
        'total_count': total_count,
        'timestamp': datetime.now().isoformat(),
        'completion_rate': len(completed_ids) / total_count * 100
    }
    with open('migration_checkpoint.json', 'w') as f:
        json.dump(checkpoint, f, indent=2)

def load_checkpoint():
    try:
        with open('migration_checkpoint.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def process_images_parallel(image_urls, ado_pat, script_config, gitlab_project, max_workers=5):
    """Process multiple images in parallel"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(
                utils.download_ado_image, url, ado_pat, script_config
            ): url for url in image_urls
        }
        
        results = {}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                filename, image_bytes = future.result()
                if filename and image_bytes:
                    # Upload to GitLab
                    markdown_link = gitlab_interaction.upload_image_and_get_markdown(
                        gitlab_project, filename, image_bytes
                    )
                    results[url] = markdown_link
            except Exception as e:
                logger.error(f"Failed to process image {url}: {e}")
                results[url] = None
        
        return results

def batch_create_gitlab_items(items_data, gitlab_project, gitlab_group, max_workers=3):
    """Create multiple GitLab items in parallel (with rate limiting)"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for item_data in items_data:
            if item_data['type'] == 'epic':
                future = executor.submit(
                    gitlab_interaction.create_gitlab_epic, 
                    gitlab_group, item_data['payload'], item_data['ado_id']
                )
            else:
                future = executor.submit(
                    gitlab_interaction.create_gitlab_issue, 
                    gitlab_project, item_data['payload'], item_data['ado_id']
                )
            futures.append((future, item_data))
        
        results = []
        for future, item_data in futures:
            try:
                result = future.result()
                results.append((item_data['ado_id'], result))
            except Exception as e:
                logger.error(f"Failed to create item for ADO #{item_data['ado_id']}: {e}")
                results.append((item_data['ado_id'], None))
        
        return results

def parse_ado_date_to_gitlab_format(ado_date_str):
    # ... (function remains the same) ...
    if not ado_date_str:
        return None
    try:
        if isinstance(ado_date_str, datetime): 
            dt_obj = ado_date_str
        else:
            dt_obj = datetime.fromisoformat(ado_date_str.replace('Z', '+00:00'))
        return dt_obj.strftime('%Y-%m-%d')
    except ValueError:
        logger.warning(f"Could not parse date string from ADO: {ado_date_str}")
        try:
            dt_obj = datetime.strptime(ado_date_str.split('T')[0], '%Y-%m-%d')
            return dt_obj.strftime('%Y-%m-%d')
        except ValueError:
            logger.warning(f"Further attempt to parse date string {ado_date_str} as YYYY-MM-DD also failed.")
            return None
    except Exception as e:
        logger.error(f"Unexpected error parsing date string {ado_date_str}: {e}")
        return None

def main():
    logger.info("--- Starting ADO to GitLab Migration Script ---")
    # ... (initial setup, config loading, client init remains the same) ...
    script_config = config_loader.load_migration_config()
    if script_config is None:
        logger.critical("Exiting due to configuration loading failure.")
        sys.exit(1)

    _, ado_wit_client, ado_core_client = ado_client.init_ado_connection(AZURE_ORG_URL, AZURE_PAT)
    if not ado_wit_client or not ado_core_client: sys.exit(1)
    
    try: 
        ado_project_details = ado_core_client.get_project(AZURE_PROJECT)
        logger.info(f"Azure DevOps Target Project Verified: {ado_project_details.name} (ID: {ado_project_details.id})")
    except Exception as e:
        logger.critical(f"Failed to verify ADO Project '{AZURE_PROJECT}'. Error: {e}", exc_info=True)
        sys.exit(1)

    gl, gitlab_project, gitlab_group = gitlab_interaction.init_gitlab_connection(
        GITLAB_URL, GITLAB_PAT, GITLAB_PROJECT_ID, script_config
    )
    if not gl or not gitlab_project or not gitlab_group: sys.exit(1)

    ado_id_to_gitlab = config_loader.load_mapping(filepath=ADO_GITLAB_MAP_FILE)
    logger.info(f"Loaded {len(ado_id_to_gitlab)} existing ADO-GitLab mappings from {ADO_GITLAB_MAP_FILE}.")


    # --- Determine fields to select for ADO query ---
    # For the initial WIQL query, you only need System.Id to get the list of IDs.
    # Other fields will be fetched in the batch call.
    fields_for_wiql_query = ["[System.Id]"]
    
    # --- Define fields for the batch get_work_items_batch call ---
    ado_priority_field_ref = script_config.get('ado_priority_field_ref_name')
    fields_for_batch_get = [
        "System.Id", "System.Title", "System.WorkItemType", 
        "System.State", "System.Tags", "System.CreatedDate", "System.CreatedBy", # Added CreatedDate/By for comments
        "System.AreaPath", "System.IterationPath"
    ]
    
    ado_desc_fields_config = script_config.get('ado_description_fields', ["System.Description"]) 
    if not ado_desc_fields_config: 
        ado_desc_fields_config = ["System.Description"]
        
    for field_ref in ado_desc_fields_config:
        if field_ref and field_ref not in fields_for_batch_get: 
            fields_for_batch_get.append(field_ref)
            
    if ado_priority_field_ref and ado_priority_field_ref not in fields_for_batch_get:
        fields_for_batch_get.append(ado_priority_field_ref)
    
    # Get all ADO work item references (just IDs primarily)
    ado_work_item_refs = ado_client.query_ado_work_item_refs(ado_wit_client, AZURE_PROJECT, fields_for_wiql_query)
    if not ado_work_item_refs: 
        logger.info("No work items to process based on ADO query.")
        # sys.exit(0) # Optional: exit if no items
    else:
        logger.info(f"Found {len(ado_work_item_refs)} total work item references from ADO WIQL query.")

    # Extract IDs to fetch in batch
    all_ado_ids = [wi_ref.id for wi_ref in ado_work_item_refs]
    
    # --- Batch fetch ADO work item details ---
    # Implement chunking if you expect more than ~200 items due to API limits
    chunk_size = script_config.get('ado_batch_fetch_size', 100) # Configurable chunk size
    all_ado_work_item_details_list = []

    for i in range(0, len(all_ado_ids), chunk_size):
        id_chunk = all_ado_ids[i:i + chunk_size]
        logger.info(f"Fetching details for ADO ID chunk: {id_chunk[:3]}... to {id_chunk[-1:]} (Total: {len(id_chunk)})")
        
        # Set expand_relations=False for this primary fetch, relations are fetched later per item
        # Or, if you *always* need relations for every item, set it to True here,
        # but be aware it increases payload size.
        # For now, setting to False for primary creation loop.
        batch_details = ado_client.get_ado_work_items_batch(
            ado_wit_client, 
            id_chunk, 
            fields=fields_for_batch_get, 
            expand_relations=False, # Fetch relations separately later IF needed for linking to avoid large initial payloads
            error_policy="omit" # or "fail"
        )
        all_ado_work_item_details_list.extend(batch_details)
        logger.info(f"Fetched {len(batch_details)} details in this chunk. Total details fetched so far: {len(all_ado_work_item_details_list)}")


    iteration_node_cache = {}
    logger.info(f"--- Phase 1: Creating Epics and Issues (from {len(all_ado_work_item_details_list)} fetched details) ---")
    
    # Now loop through the fetched details instead of wi_ref
    for ado_work_item_details in all_ado_work_item_details_list:
        if not ado_work_item_details or not hasattr(ado_work_item_details, 'id') or not hasattr(ado_work_item_details, 'fields'):
            logger.warning(f"Skipping invalid work item detail object: {ado_work_item_details}")
            continue

        ado_work_item_id = ado_work_item_details.id
        logger.info(f"Processing ADO Work Item #{ado_work_item_id} (from batch)...")
        
        gitlab_item_for_comments = None
        gitlab_item_type_for_comments = None

        if ado_work_item_id in ado_id_to_gitlab:
            existing_mapping = ado_id_to_gitlab[ado_work_item_id]
            logger.info(f"ADO #{ado_work_item_id} already mapped to GitLab {existing_mapping['type']} #{existing_mapping['id']}. Will not re-create item.")
            try:
                gitlab_item_type_for_comments = existing_mapping['type']
                # ... (rest of your existing item handling logic for comments, using existing_mapping['id']) ...
                if gitlab_item_type_for_comments == "epic":
                    gitlab_item_for_comments = gitlab_interaction.call_with_retry(
                        f"fetch existing epic {existing_mapping['id']}", gitlab_group.epics.get, existing_mapping['id']
                    )
                else: 
                    gitlab_item_for_comments = gitlab_interaction.call_with_retry(
                        f"fetch existing issue {existing_mapping['id']}", gitlab_project.issues.get, existing_mapping['id']
                    )

            except Exception as e_fetch_existing:
                logger.error(f"Failed to fetch existing GitLab {gitlab_item_type_for_comments or 'item'} #{existing_mapping.get('id')} for ADO #{ado_work_item_id}. Error: {e_fetch_existing}")
                gitlab_item_for_comments = None

        else: 
            try:
                # ado_work_item_details is already fetched
                title = ado_work_item_details.fields.get("System.Title", f"Untitled ADO Item {ado_work_item_id}")
                
                # ... (rest of your logic for description, labels, milestone, item creation) ...
                # ... (using ado_work_item_details.fields.get(...) directly) ...
                concatenated_description_html = ""
                first_desc_field = True
                for field_ref_name in ado_desc_fields_config: 
                    field_html_content = ado_work_item_details.fields.get(field_ref_name, "")
                    if field_html_content and isinstance(field_html_content, str): 
                        if not first_desc_field and concatenated_description_html: 
                            concatenated_description_html += "\n<hr/>\n" 
                        concatenated_description_html += field_html_content
                        first_desc_field = False if concatenated_description_html.strip() else True 
                
                if script_config.get('migrate_comment_images', False): 
                    logger.debug(f"  Attempting to migrate images in main description for ADO #{ado_work_item_id}")
                    concatenated_description_html = utils.migrate_images_in_html_text(
                        concatenated_description_html, gitlab_project, AZURE_PAT, script_config, gitlab_interaction
                    )
                # description_md = utils.basic_html_to_markdown(concatenated_description_html)
                description_md = utils.html_to_markdown(concatenated_description_html)

                ado_type = ado_work_item_details.fields.get("System.WorkItemType", "WorkItem")
                ado_state = ado_work_item_details.fields.get("System.State", "Undefined")
                ado_priority_val = ado_work_item_details.fields.get(ado_priority_field_ref) if ado_priority_field_ref else None
                ado_tags_string = ado_work_item_details.fields.get("System.Tags", "")
                ado_area_path = ado_work_item_details.fields.get("System.AreaPath", "")
                ado_iteration_path = ado_work_item_details.fields.get("System.IterationPath", "")
                
                migration_footer = f"\n\n---\nMigrated from ADO #{ado_work_item_id} (Type: {ado_type}, State: {ado_state}"
                # ... (rest of migration footer generation) ...
                if ado_priority_val is not None: migration_footer += f", Priority: {ado_priority_val}"
                if ado_tags_string: migration_footer += f", Original ADO Tags: {ado_tags_string}"
                if ado_area_path: migration_footer += f", Original Area: {ado_area_path}"
                if ado_iteration_path: migration_footer += f", Original Iteration: {ado_iteration_path}"
                migration_footer += ")"
                final_description_for_gitlab = description_md + migration_footer

                labels_to_apply_names = []
                gitlab_target_type_str = script_config.get('ado_to_gitlab_type', {}).get(ado_type, script_config.get('default_gitlab_type', 'issue'))
                gitlab_item_type_for_comments = gitlab_target_type_str # Store for comment migration

                state_mapping_config = script_config.get('ado_state_to_gitlab_labels', {}).get(ado_state)
                action_close_issue = False
                # ... (rest of label generation from state, priority, type, tags, area path) ...
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

                if script_config.get('migrate_ado_tags', False) and ado_tags_string:
                    tag_prefix = script_config.get('ado_tag_label_prefix', '')
                    parsed_tags = [tag.strip() for tag in ado_tags_string.split(';') if tag.strip()]
                    for tag in parsed_tags: labels_to_apply_names.append(f"{tag_prefix}{tag}")
                    logger.info(f"  Prepared ADO tags for migration: {parsed_tags} with prefix '{tag_prefix}'")

                if script_config.get('migrate_area_paths_to_labels', False) and ado_area_path:
                    area_prefix = script_config.get('area_path_label_prefix', 'area::')
                    strategy = script_config.get('area_path_handling_strategy', 'last_segment_only')
                    level_sep = script_config.get('area_path_level_separator', '\\')
                    gitlab_sep = script_config.get('gitlab_area_path_label_separator', '::')
                    
                    path_segments = [seg.strip() for seg in ado_area_path.split(level_sep) if seg.strip()]
                    if path_segments and path_segments[0].lower() == AZURE_PROJECT.lower():
                        path_segments.pop(0)

                    if path_segments:
                        # ... (area path label generation logic) ...
                        if strategy == 'last_segment_only':
                            labels_to_apply_names.append(f"{area_prefix}{path_segments[-1]}")
                        elif strategy == 'full_path':
                            labels_to_apply_names.append(f"{area_prefix}{gitlab_sep.join(path_segments)}")
                        elif strategy == 'all_segments':
                            for segment in path_segments:
                                labels_to_apply_names.append(f"{area_prefix}{segment}")
                        elif strategy == 'all_segments_hierarchical':
                            current_hier_path = ""
                            for i, segment in enumerate(path_segments):
                                if i == 0:
                                    current_hier_path = segment
                                else:
                                    current_hier_path += f"{gitlab_sep}{segment}"
                                labels_to_apply_names.append(f"{area_prefix}{current_hier_path}")
                        logger.info(f"  Prepared Area Path '{ado_area_path}' as labels with strategy '{strategy}'")
                
                final_gl_labels = []
                for label_name in list(set(labels_to_apply_names)): 
                    if not label_name: continue 
                    created_label_name = gitlab_interaction.get_or_create_gitlab_label(gitlab_project, label_name, script_config, random)
                    if created_label_name:
                        final_gl_labels.append(created_label_name)
                
                item_payload = {'title': title, 'description': final_description_for_gitlab, 'labels': final_gl_labels}

                if script_config.get('migrate_iteration_paths_to_milestones', False) and ado_iteration_path:
                    # ... (milestone logic) ...
                    logger.debug(f"  Processing Iteration Path: {ado_iteration_path}")
                    milestone_title_map = script_config.get('iteration_path_to_milestone_title_map', {})
                    milestone_title = milestone_title_map.get(ado_iteration_path)
                    
                    if not milestone_title: 
                        path_segments = [seg.strip() for seg in ado_iteration_path.split(script_config.get('area_path_level_separator', '\\')) if seg.strip()]
                        if path_segments:
                            milestone_title = path_segments[-1]
                    
                    if milestone_title:
                        start_date_str, due_date_str = None, None
                        if ado_iteration_path not in iteration_node_cache:
                            logger.debug(f"    Fetching details for Iteration Path node: {ado_iteration_path}")
                            node_details = ado_client.get_ado_classification_node_details(
                                ado_wit_client, AZURE_PROJECT, 'iterations', ado_iteration_path, depth=0
                            )
                            iteration_node_cache[ado_iteration_path] = node_details
                        else:
                            logger.debug(f"    Using cached details for Iteration Path node: {ado_iteration_path}")
                            node_details = iteration_node_cache[ado_iteration_path]

                        if node_details and hasattr(node_details, 'attributes') and node_details.attributes:
                            start_date_raw = node_details.attributes.get('startDate')
                            finish_date_raw = node_details.attributes.get('finishDate')
                            start_date_str = parse_ado_date_to_gitlab_format(start_date_raw)
                            due_date_str = parse_ado_date_to_gitlab_format(finish_date_raw)
                            logger.debug(f"    ADO Iteration dates: Start='{start_date_raw}' -> '{start_date_str}', Finish='{finish_date_raw}' -> '{due_date_str}'")
                        
                        milestone_obj = gitlab_interaction.get_or_create_gitlab_milestone(
                            gitlab_project, milestone_title, start_date_str, due_date_str
                        )
                        if milestone_obj and hasattr(milestone_obj, 'id'):
                            item_payload['milestone_id'] = milestone_obj.id
                            logger.info(f"  Assigned to GitLab Milestone: '{milestone_title}' (ID: {milestone_obj.id})")
                        else:
                            logger.warning(f"  Could not find or create GitLab Milestone for Iteration Path: '{ado_iteration_path}' (Title: '{milestone_title}')")
                    else:
                        logger.warning(f"  Could not determine a milestone title for Iteration Path: {ado_iteration_path}")

                created_gl_item = None
                if gitlab_target_type_str == "epic":
                    if 'milestone_id' in item_payload:
                        logger.info(f"  Note: Milestone ID {item_payload['milestone_id']} prepared but GitLab Epics don't directly use project milestones.")
                    created_gl_item = gitlab_interaction.create_gitlab_epic(gitlab_group, item_payload, ado_work_item_id)
                else: # issue
                    created_gl_item = gitlab_interaction.create_gitlab_issue(gitlab_project, item_payload, ado_work_item_id)
                
                if created_gl_item: 
                    if gitlab_target_type_str == "issue" and action_close_issue:
                        gitlab_interaction.close_gitlab_issue(gitlab_project, created_gl_item.iid)
                    gitlab_item_for_comments = created_gl_item 
                    ado_id_to_gitlab[ado_work_item_id] = {'type': gitlab_target_type_str, 'id': created_gl_item.iid, 'gitlab_global_id': created_gl_item.id}
                    config_loader.save_mapping(ado_id_to_gitlab, filepath=ADO_GITLAB_MAP_FILE) 
                else: 
                    logger.error(f"  Failed to create GitLab {gitlab_target_type_str} for ADO #{ado_work_item_id}. Skipping further processing for this item.")
                    continue 

            except Exception as e_general_create:
                logger.error(f"  UNEXPECTED ERROR during item creation phase for ADO #{ado_work_item_id}: {e_general_create}", exc_info=True) # Added error object to log
                continue

        # --- Migrate Comments (with images) ---
        if script_config.get('migrate_comments', False) and gitlab_item_for_comments:
            logger.info(f"  Fetching comments for ADO #{ado_work_item_id} (GitLab {gitlab_item_type_for_comments} #{getattr(gitlab_item_for_comments, 'iid', 'N/A')})...")
            # Use ado_work_item_details.id directly as ado_work_item_id
            ado_comments_list = ado_client.get_ado_work_item_comments(ado_wit_client, AZURE_PROJECT, ado_work_item_id)
            if ado_comments_list:
                logger.info(f"  Found {len(ado_comments_list)} comments in ADO for #{ado_work_item_id}. Migrating...")
                # ... (rest of your comment migration logic) ...
                for ado_comment in ado_comments_list: 
                    try:
                        comment_text_html = ado_comment.text
                        if script_config.get('migrate_comment_images', False): 
                            logger.debug(f"    Attempting to migrate images in comment ID {ado_comment.id} for ADO #{ado_work_item_id}")
                            comment_text_html = utils.migrate_images_in_html_text(
                                comment_text_html, gitlab_project, AZURE_PAT, script_config, gitlab_interaction
                            )
                        # comment_text_md = utils.basic_html_to_markdown(comment_text_html)
                        comment_text_md = utils.html_to_markdown(comment_text_html)

                        # --- Get author and timestamp from the ADO work item detail for comments if needed ---
                        # This part assumes ado_comment object has 'created_by' and 'created_date'
                        # If not, you might need to adjust where you get this info.
                        # The `ado_work_item_details` has `CreatedDate` and `CreatedBy` for the main item.
                        # ADO comments usually have their own `createdBy` and `createdDate`.
                        author_identity = getattr(ado_comment, 'created_by', None) # Make sure ado_comment has this
                        if not author_identity: # Fallback if comment object itself doesn't have it
                            author_identity = ado_work_item_details.fields.get("System.CreatedBy")

                        author_repr = utils.get_ado_user_representation(author_identity, script_config)
                        
                        ts_dt = getattr(ado_comment, 'created_date', None) # Make sure ado_comment has this
                        if not ts_dt: # Fallback
                            ts_dt_str = ado_work_item_details.fields.get("System.CreatedDate")
                            if ts_dt_str: ts_dt = datetime.fromisoformat(ts_dt_str.replace('Z', '+00:00'))
                        
                        if ts_dt:
                            if ts_dt.tzinfo is None: ts_dt_utc = ts_dt.replace(tzinfo=timezone.utc)
                            else: ts_dt_utc = ts_dt.astimezone(timezone.utc)
                            ts_str = ts_dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
                            header_format = script_config.get('migrated_comment_header_format', "**Comment from ADO by {author} on {timestamp}:**\n\n")
                            header = header_format.format(author=author_repr, timestamp=ts_str)
                            note_body = f"{header}{comment_text_md}"
                            payload = {'body': note_body}
                            try: payload['created_at'] = ts_dt_utc.isoformat()
                            except: pass 
                            
                            gitlab_interaction.add_gitlab_note(gitlab_item_for_comments, payload, ado_comment.id, gitlab_item_type_for_comments, getattr(gitlab_item_for_comments, 'iid', 'N/A'))
                        else:
                            logger.warning(f"    Could not determine timestamp for ADO comment ID {ado_comment.id if ado_comment else 'N/A'}. Skipping note creation.")
                            
                    except Exception as e_comm_indiv: 
                        logger.warning(f"    Error processing individual ADO comment ID {ado_comment.id if ado_comment else 'N/A'}. Error: {e_comm_indiv}", exc_info=True)
            else:
                logger.info(f"  No comments found in ADO for #{ado_work_item_id} to migrate.")
        
    # --- Phase 2: Link Parent/Child and Other Relations ---
    logger.info("--- Phase 2: Linking Parent/Child and Other Relations ---")
    # Important: For relation fetching, you DO need to expand relations.
    # You can either:
    # 1. Re-fetch items that need relation processing (if not too many)
    # 2. Or, if expand_relations=True was used in the batch get, you can use those.
    #    Let's assume for now we will re-fetch with expand=True for linking phase
    #    to keep the initial batch payload smaller if relations aren't always needed.

    if not all_ado_ids: # Use all_ado_ids from the initial WIQL query
        logger.info("No work items to process for linking (based on initial query).")
    else:
        # Chunk the IDs again for fetching relations if needed
        for i in range(0, len(all_ado_ids), chunk_size):
            id_chunk_for_relations = all_ado_ids[i:i + chunk_size]
            logger.info(f"Fetching relations for ADO ID chunk: {id_chunk_for_relations[:3]}... (Total: {len(id_chunk_for_relations)})")

            # Fetch with expand_relations=True this time
            items_with_relations_batch = ado_client.get_ado_work_items_batch(
                ado_wit_client,
                id_chunk_for_relations,
                fields=["System.Id", "System.Links.LinkType"], # Only need ID and links for this phase
                expand_relations=True,
                error_policy="omit"
            )

            for ado_item_with_relations in items_with_relations_batch:
                if not ado_item_with_relations or not hasattr(ado_item_with_relations, 'id'):
                    continue
                source_ado_id = ado_item_with_relations.id
                if source_ado_id not in ado_id_to_gitlab: 
                    logger.debug(f"  Source ADO #{source_ado_id} not in mapping. Skipping link processing for it.")
                    continue 
            
                source_gitlab_info = ado_id_to_gitlab[source_ado_id]
                logger.info(f"Processing links for source ADO #{source_ado_id} (GitLab {source_gitlab_info['type']} #{source_gitlab_info['id']})...")
            
                relations = getattr(ado_item_with_relations, "relations", None)
                if relations:
                    # ... (rest of your relation processing logic remains the same) ...
                    for rel in relations:
                        target_ado_id = -1 
                        try:
                            rel_url_str = getattr(rel, 'url', "")
                            if not rel_url_str:
                                logger.debug(f"  Skipping relation with empty URL for source ADO #{source_ado_id}")
                                continue
                            
                            work_item_url_pattern = r"https?://[^/]+(?:/[^/]+)?/[^/]+/_apis/wit/workitems/(\d+)"
                            match_re = re.search(work_item_url_pattern, rel_url_str, re.IGNORECASE)

                            if not match_re:
                                logger.debug(f"  Skipping non-standard work item relation URL: '{rel_url_str}' for source ADO #{source_ado_id}")
                                continue
                            target_ado_id_str = match_re.group(1)
                            target_ado_id = int(target_ado_id_str)
                            
                            ado_link_ref_name = rel.rel 
                            ado_link_friendly_name = getattr(rel, 'attributes', {}).get('name', 'UnknownLinkType')
                            logger.debug(f"  Found ADO link: Source ADO #{source_ado_id} --[{ado_link_friendly_name} ({ado_link_ref_name})]--> Target ADO #{target_ado_id}")
                            
                            if target_ado_id not in ado_id_to_gitlab:
                                logger.info(f"    Target ADO #{target_ado_id} for link from ADO #{source_ado_id} was not mapped. Skipping.")
                                continue
                            target_gitlab_info = ado_id_to_gitlab[target_ado_id]
                            
                            is_hierarchical, parent_gl, child_gl = False, None, None
                            if ado_link_ref_name == "System.LinkTypes.Hierarchy-Forward": 
                                parent_gl, child_gl, is_hierarchical = target_gitlab_info, source_gitlab_info, True
                            elif ado_link_ref_name == "System.LinkTypes.Hierarchy-Reverse":
                                parent_gl, child_gl, is_hierarchical = source_gitlab_info, target_gitlab_info, True
                            
                            if is_hierarchical:
                                if parent_gl['type'] == 'epic' and child_gl['type'] == 'issue':
                                    gitlab_interaction.link_gitlab_epic_issue(gitlab_group, parent_gl['id'], child_gl['gitlab_global_id'])
                                elif parent_gl['type'] == 'issue' and child_gl['type'] == 'issue': # Parent/child between issues (Task > Task)
                                     # GitLab doesn't have direct parent/child for issues like ADO tasks.
                                     # It uses "blocks" or "is_blocked_by" or just "relates_to".
                                     # Or child issues of an Epic.
                                     # For now, linking as 'relates_to'. You might want a specific config.
                                    logger.info(f"    Mapping ADO Issue-to-Issue hierarchy (ADO Task to Task) as 'relates_to' in GitLab for GL #{parent_gl['id']} and GL #{child_gl['id']}.")
                                    gitlab_interaction.link_gitlab_issues(gitlab_project, parent_gl['id'], child_gl['id'], 'relates_to')
                                else:
                                    logger.info(f"    Skipping hierarchical link: Unsupported GitLab type combination. Parent: {parent_gl['type']}, Child: {child_gl['type']}")
                                continue 
                            
                            mapped_gl_link_type = script_config.get('ado_to_gitlab_link_type_mapping', {}).get(ado_link_ref_name) or \
                                                  script_config.get('default_gitlab_link_type')
                            if mapped_gl_link_type and mapped_gl_link_type not in ["_parent_of_current_", "_child_of_current_"]:
                                if source_gitlab_info['type'] == 'issue' and target_gitlab_info['type'] == 'issue':
                                    gitlab_interaction.link_gitlab_issues(gitlab_project, source_gitlab_info['id'], target_gitlab_info['id'], mapped_gl_link_type)
                                else: 
                                    logger.info(f"    Skipping generic link type '{mapped_gl_link_type}': Both items must be GitLab 'issues' for this link type.")
                            elif ado_link_ref_name not in script_config.get('ado_to_gitlab_link_type_mapping', {}):
                                if script_config.get('ado_to_gitlab_link_type_mapping', {}).get(ado_link_ref_name) is not None: # Only if explicitly set to null in mapping
                                    logger.info(f"    ADO Link type '{ado_link_ref_name}' ({ado_link_friendly_name}) from ADO #{source_ado_id} to #{target_ado_id} is explicitly ignored in config. Skipping.")
                                # else implicitly skipped if not in mapping and no default or default is null
                        except Exception as e_rel_proc: 
                            logger.warning(f"    Error processing relation for ADO source {source_ado_id} to target {target_ado_id}: {getattr(rel, 'url', 'N/A')}. Error: {e_rel_proc}", exc_info=True)
                else: 
                    logger.debug(f"  No relations found for ADO source #{source_ado_id} (expanded fetch).")
            if not items_with_relations_batch: # If a whole chunk fetch failed.
                 logger.warning(f"Relation fetching failed for chunk starting with ADO ID {id_chunk_for_relations[0] if id_chunk_for_relations else 'N/A'}")


    logger.info("--- Migration Script Finished ---")

if __name__ == '__main__':
    main()