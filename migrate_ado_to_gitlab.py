# import json
# import random
# import os
# import yaml
# import logging
# import sys
# import traceback
# import re # For basic_html_to_markdown's regex usage
# import time # For retry delays
# import requests # For requests.exceptions used in call_with_retry
# from datetime import datetime, timezone # For ISO formatted dates and current time
# from azure.devops.connection import Connection
# from msrest.authentication import BasicAuthentication
# import gitlab
# from gitlab.exceptions import GitlabHttpError, GitlabCreateError, GitlabGetError # For specific error handling

# # --- Configuration: Ensure this file exists and is correctly populated ---
# try:
#     from config import AZURE_ORG_URL, AZURE_PROJECT, AZURE_PAT, GITLAB_URL, GITLAB_PAT, GITLAB_PROJECT_ID
# except ImportError:
#     # Fallback for print if logger not yet configured or if this is run directly without full setup
#     print("CRITICAL: config.py not found or missing required variables. Please create it with your credentials and project details.")
#     sys.exit(1)

# # --- Script Configuration Constants ---
# ADO_GITLAB_MAP_FILE = 'ado_gitlab_map.json'
# MIGRATION_CONFIG_FILE = 'migration_config.yaml'
# LOG_FILE = 'migration_log.txt'
# MAX_RETRIES = 3
# RETRY_DELAY_SECONDS = 5


# # --- Logging Setup ---
# logger = logging.getLogger('ado_gitlab_migrator')
# logger.setLevel(logging.DEBUG) # Capture all levels of logs

# # Prevent duplicate handlers if script is re-imported or run in certain environments
# if not logger.handlers:
#     # File Handler - for persistent logs
#     try:
#         file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8') # Append mode
#         file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
#         file_handler.setFormatter(file_formatter)
#         file_handler.setLevel(logging.INFO) # Log INFO and above to file by default
#         logger.addHandler(file_handler)
#     except Exception as e:
#         print(f"CRITICAL: Failed to configure file logger for {LOG_FILE}: {e}. File logging will be unavailable.")

#     # Console Handler - for immediate feedback
#     console_handler = logging.StreamHandler(sys.stdout)
#     console_formatter = logging.Formatter('%(levelname)s - %(message)s') # Simpler format for console
#     console_handler.setFormatter(console_formatter)
#     console_handler.setLevel(logging.INFO) # Show INFO and above on console
#     logger.addHandler(console_handler)

# # --- Silence overly verbose logs from underlying libraries ---
# logging.getLogger("gitlab").setLevel(logging.WARNING)
# logging.getLogger("urllib3").setLevel(logging.WARNING)
# logging.getLogger("msrest").setLevel(logging.INFO)


# # --- Helper Functions ---
# def load_mapping(filepath):
#     if os.path.exists(filepath):
#         try:
#             with open(filepath, 'r', encoding='utf-8') as f:
#                 mapping_str_keys = json.load(f)
#                 mapping_int_keys = {int(k): v for k, v in mapping_str_keys.items()}
#                 logger.debug(f"Successfully loaded and parsed mapping from {filepath}")
#                 return mapping_int_keys
#         except (json.JSONDecodeError, ValueError) as e:
#             logger.warning(f"Mapping file {filepath} is corrupted or has invalid format ({e}). Starting with an empty map.")
#             return {}
#         except Exception as e:
#             logger.error(f"Could not load mapping file {filepath}", exc_info=True)
#             return {}
#     logger.info(f"Mapping file {filepath} not found. Starting with an empty map.")
#     return {}

# def save_mapping(filepath, mapping_data):
#     try:
#         with open(filepath, 'w', encoding='utf-8') as f:
#             json.dump(mapping_data, f, indent=2)
#         logger.debug(f"Successfully saved mapping to {filepath}")
#     except Exception as e:
#         logger.error(f"Could not save mapping file {filepath}", exc_info=True)

# def load_migration_config(filepath):
#     if os.path.exists(filepath):
#         try:
#             with open(filepath, 'r', encoding='utf-8') as f:
#                 config_data = yaml.safe_load(f)
#                 logger.info(f"Successfully loaded migration configuration from {filepath}")
#                 return config_data
#         except yaml.YAMLError as e:
#             logger.error(f"Could not parse YAML configuration file {filepath}: {e}", exc_info=True)
#             return None
#         except Exception as e:
#             logger.error(f"Could not load configuration file {filepath}", exc_info=True)
#             return None
#     else:
#         logger.error(f"Migration configuration file {filepath} not found.")
#         return None

# def get_ado_user_representation(ado_user_identity, config_data):
#     if not ado_user_identity: return "Unknown ADO User"
#     display_name = getattr(ado_user_identity, 'display_name', 'Unknown Name')
#     unique_name = getattr(ado_user_identity, 'unique_name', None) or \
#                   getattr(ado_user_identity, 'name', None) 
#     user_map = config_data.get('user_mapping', {})
#     mapped_gitlab_user = None
#     if unique_name and unique_name in user_map: mapped_gitlab_user = user_map[unique_name]
#     elif display_name in user_map: mapped_gitlab_user = user_map[display_name]
#     if mapped_gitlab_user: return f"GitLab user '{mapped_gitlab_user}' (ADO: {display_name})"
#     default_gitlab_user = user_map.get("_default_")
#     if default_gitlab_user: return f"'{default_gitlab_user}' (Original ADO user: {display_name})"
#     user_details = f"ADO user: {display_name}"
#     if unique_name and unique_name.lower() != display_name.lower(): user_details += f" [{unique_name}]"
#     return user_details

# def basic_html_to_markdown(html_content):
#     if not html_content: return ""
#     text = str(html_content)
#     text = text.replace("<br>", "\n").replace("<br />", "\n").replace("<br/>", "\n")
#     text = text.replace("</p>", "\n").replace("<p>", "")
#     text = text.replace("<strong>", "**").replace("</strong>", "**").replace("<b>", "**").replace("</b>", "**")
#     text = text.replace("<em>", "*").replace("</em>", "*").replace("<i>", "*").replace("</i>", "*")
#     text = text.replace("<u>", "_").replace("</u>", "_")
#     text = text.replace("<ul>", "\n").replace("</ul>", "\n").replace("<ol>", "\n").replace("</ol>", "\n")
#     text = text.replace("<li>", "\n- ").replace("</li>", "")
#     try:
#         text = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.IGNORECASE | re.DOTALL)
#         text = re.sub(r'<[^>]+>', '', text) # Basic strip of remaining tags
#     except Exception: logger.debug("Regex issue in basic_html_to_markdown.")
#     return text.strip()

# def call_with_retry(action_description, gitlab_api_call, *args, **kwargs):
#     """Wrapper to call GitLab API functions with retry logic."""
#     for attempt in range(MAX_RETRIES):
#         try:
#             return gitlab_api_call(*args, **kwargs)
#         except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout, GitlabHttpError) as e:
#             is_retryable_http_error = isinstance(e, GitlabHttpError) and e.response_code in [429, 500, 502, 503, 504]
#             is_timeout_error = isinstance(e, (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout))

#             if not (is_retryable_http_error or is_timeout_error):
#                 logger.error(f"GITLAB API ERROR (non-retryable) during '{action_description}': {e}", exc_info=False)
#                 raise 
            
#             logger.warning(f"Timeout/Retryable Server Error during '{action_description}' (Attempt {attempt + 1}/{MAX_RETRIES}). Error: {e}. Retrying in {RETRY_DELAY_SECONDS * (attempt + 1)}s...")
#             if attempt < MAX_RETRIES - 1:
#                 time.sleep(RETRY_DELAY_SECONDS * (attempt + 1)) 
#             else:
#                 logger.error(f"Max retries reached for '{action_description}'. Error: {e}", exc_info=True)
#                 raise 
#         except GitlabCreateError as e_create: 
#             if any(msg in str(e_create).lower() for msg in ["has already been taken", "already related", "already assigned", "member already exists"]):
#                 logger.info(f"INFO during '{action_description}': Item already exists or link/assignment is duplicate. Message: {e_create}")
#                 return None 
#             else:
#                 logger.error(f"GITLAB CREATE ERROR during '{action_description}': {e_create}", exc_info=True)
#                 raise
#         except GitlabGetError as e_get: 
#             if e_get.response_code == 404:
#                 logger.debug(f"GitLab GET request for '{action_description}' resulted in 404 (Not Found).")
#                 raise 
#             else:
#                 logger.error(f"GITLAB GET ERROR during '{action_description}': {e_get}", exc_info=True)
#                 raise
#         except Exception as e: 
#             logger.error(f"UNEXPECTED ERROR during '{action_description}': {e}", exc_info=True)
#             raise


# # --- Main Script ---
# def main():
#     logger.info("--- Starting ADO to GitLab Migration Script ---")
#     logger.info(f"Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

#     logger.info(f"Loading migration configuration from {MIGRATION_CONFIG_FILE}...")
#     script_config = load_migration_config(MIGRATION_CONFIG_FILE)
#     if script_config is None:
#         logger.critical("Exiting due to configuration loading failure.")
#         sys.exit(1)

#     logger.info(f"Connecting to Azure DevOps organization: {AZURE_ORG_URL}...")
#     try:
#         credentials = BasicAuthentication('', AZURE_PAT)
#         connection = Connection(base_url=AZURE_ORG_URL, creds=credentials)
#         wit_client = connection.clients.get_work_item_tracking_client()
#         core_client = connection.clients.get_core_client()
#         ado_project_details = core_client.get_project(AZURE_PROJECT)
#         logger.info(f"Azure DevOps connection successful. Target ADO Project: {ado_project_details.name} (ID: {ado_project_details.id})")
#     except Exception as e:
#         logger.critical(f"Azure DevOps connection failed. Error: {e}", exc_info=True)
#         sys.exit(1)

#     logger.info(f"Connecting to GitLab instance: {GITLAB_URL}...")
#     try:
#         gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_PAT, timeout=script_config.get('gitlab_client_timeout', 60))
#         gl.auth()
#         gitlab_project = gl.projects.get(GITLAB_PROJECT_ID)
#         gitlab_group = gl.groups.get(gitlab_project.namespace['id'])
#         logger.info(f"GitLab connection successful. Target GitLab Project: {gitlab_project.name_with_namespace}, Target Group: {gitlab_group.full_name}")
#     except Exception as e:
#         logger.critical(f"GitLab connection or project/group retrieval failed. Error: {e}", exc_info=True)
#         sys.exit(1)

#     logger.info(f"Loading ADO to GitLab mapping from {ADO_GITLAB_MAP_FILE}...")
#     ado_id_to_gitlab = load_mapping(ADO_GITLAB_MAP_FILE)
#     logger.info(f"Loaded {len(ado_id_to_gitlab)} existing mappings.")

#     logger.info(f"Querying work items from ADO project: {AZURE_PROJECT}...")
#     ado_priority_field_ref = script_config.get('ado_priority_field_ref_name')
#     fields_to_select = ["[System.Id]", "[System.Title]", "[System.Description]", "[System.WorkItemType]", "[System.State]"]
#     if ado_priority_field_ref: fields_to_select.append(f"[{ado_priority_field_ref}]")
#     wiql_query_string = f"SELECT {', '.join(fields_to_select)} FROM WorkItems WHERE [System.TeamProject] = '{AZURE_PROJECT}'"
#     wiql_payload = {'query': wiql_query_string}
#     logger.debug(f"Executing WIQL query: {wiql_query_string}")
#     ado_work_item_refs = []
#     try:
#         wiql_results_ado = wit_client.query_by_wiql(wiql_payload)
#         if wiql_results_ado and hasattr(wiql_results_ado, 'work_items') and wiql_results_ado.work_items is not None:
#             ado_work_item_refs = wiql_results_ado.work_items
#             logger.info(f"Found {len(ado_work_item_refs)} work item references in ADO.")
#         else: logger.info("No work item references found or unexpected query result structure from ADO.")
#     except Exception as e:
#         logger.critical(f"Failed to query work items from ADO. Error: {e}", exc_info=True)
#         sys.exit(1)

#     logger.info("--- Phase 1: Creating Epics and Issues (and migrating comments) ---")
#     for wi_ref in ado_work_item_refs:
#         ado_work_item_id = wi_ref.id
#         logger.info(f"Processing ADO Work Item #{ado_work_item_id}...")
#         gitlab_item_for_comments = None
#         gitlab_item_type_for_comments = None

#         if ado_work_item_id in ado_id_to_gitlab:
#             existing_mapping = ado_id_to_gitlab[ado_work_item_id]
#             logger.info(f"ADO #{ado_work_item_id} already mapped to GitLab {existing_mapping['type']} #{existing_mapping['id']}. Will not re-create item.")
#             try:
#                 gitlab_item_type_for_comments = existing_mapping['type']
#                 if gitlab_item_type_for_comments == "epic":
#                     gitlab_item_for_comments = call_with_retry(f"fetch existing epic {existing_mapping['id']}", gitlab_group.epics.get, existing_mapping['id'])
#                 else: 
#                     gitlab_item_for_comments = call_with_retry(f"fetch existing issue {existing_mapping['id']}", gitlab_project.issues.get, existing_mapping['id'])
#             except Exception as e_fetch_existing:
#                 logger.error(f"Failed to fetch existing GitLab {gitlab_item_type_for_comments or 'item'} #{existing_mapping.get('id')} for ADO #{ado_work_item_id}. Comment/Link migration might be skipped. Error: {e_fetch_existing}")
#                 gitlab_item_for_comments = None
#         else: 
#             try:
#                 ado_work_item_details = wit_client.get_work_item(ado_work_item_id, expand="Relations")
#                 title = ado_work_item_details.fields.get("System.Title", f"Untitled ADO Item {ado_work_item_id}")
#                 description_html = ado_work_item_details.fields.get("System.Description", "")
#                 description_md = basic_html_to_markdown(description_html)
#                 ado_type = ado_work_item_details.fields.get("System.WorkItemType", "WorkItem")
#                 ado_state = ado_work_item_details.fields.get("System.State", "Undefined")
#                 ado_priority_val = ado_work_item_details.fields.get(ado_priority_field_ref) if ado_priority_field_ref else None
#                 body = f"{description_md}\n\n---\nMigrated from ADO #{ado_work_item_id} (Type: {ado_type}, State: {ado_state}" + (f", Priority: {ado_priority_val}" if ado_priority_val is not None else "") + ")"
#                 labels_to_apply = []
#                 gitlab_target_type_str = script_config.get('ado_to_gitlab_type', {}).get(ado_type, script_config.get('default_gitlab_type', 'issue'))
#                 gitlab_item_type_for_comments = gitlab_target_type_str
#                 state_mapping_config = script_config.get('ado_state_to_gitlab_labels', {}).get(ado_state)
#                 action_close_issue = False
#                 if state_mapping_config and isinstance(state_mapping_config, dict):
#                     labels_to_apply.extend(state_mapping_config.get('labels', []))
#                     if state_mapping_config.get('action') == '_close_issue_': action_close_issue = True
#                 else:
#                     prefix = script_config.get('unmapped_ado_state_label_prefix', 'ado_state::')
#                     if ado_state and ado_state != "Undefined": labels_to_apply.append(f"{prefix}{ado_state}")
#                 if ado_priority_val is not None and script_config.get('ado_priority_to_gitlab_label'):
#                     priority_label = script_config['ado_priority_to_gitlab_label'].get(ado_priority_val)
#                     if priority_label: labels_to_apply.append(priority_label)
#                     else: labels_to_apply.append(f"{script_config.get('unmapped_ado_priority_label_prefix', 'ado_priority::')}{ado_priority_val}")
#                 if gitlab_target_type_str != 'epic' and ado_type: labels_to_apply.append(f"ado_type::{ado_type}")
#                 final_gl_labels = []
#                 for label_name_raw in list(set(labels_to_apply)):
#                     label_name = str(label_name_raw).strip()
#                     if not label_name: continue
#                     try:
#                         call_with_retry(f"get label {label_name}", gitlab_project.labels.get, label_name)
#                         final_gl_labels.append(label_name)
#                         logger.debug(f"  Label '{label_name}' already exists in GitLab.")
#                     except GitlabGetError as e_get_label: 
#                          if e_get_label.response_code == 404: 
#                             try:
#                                 color = "#{:06x}".format(random.randint(0, 0xFFFFFF)) if script_config.get('new_label_color_strategy', 'random') == 'random' else "#C0C0C0"
#                                 call_with_retry(f"create label {label_name}", gitlab_project.labels.create, {'name': label_name, 'color': color})
#                                 logger.info(f"  Created GitLab label: {label_name}")
#                                 final_gl_labels.append(label_name)
#                             except Exception as e_create_label_retry: 
#                                 logger.warning(f"  Could not create label '{label_name}' after retries. Error: {e_create_label_retry}. Skipping.")
#                          else: 
#                             logger.warning(f"  Error getting label '{label_name}'. Error: {e_get_label}. Skipping.")
#                     except Exception as e_label_generic: 
#                         logger.warning(f"  An unexpected error occurred with label '{label_name}'. Error: {e_label_generic}. Skipping.")

#                 item_payload = {'title': title, 'description': body, 'labels': final_gl_labels}
#                 created_gl_item = None
#                 action_description_create = f"create GitLab {gitlab_target_type_str} for ADO #{ado_work_item_id}"
#                 if gitlab_target_type_str == "epic":
#                     created_gl_item = call_with_retry(action_description_create, gitlab_group.epics.create, item_payload)
#                 else:
#                     created_gl_item = call_with_retry(action_description_create, gitlab_project.issues.create, item_payload)
                
#                 if created_gl_item: 
#                     logger.info(f"  SUCCESS: Created GitLab {gitlab_target_type_str} #{created_gl_item.iid} for ADO #{ado_work_item_id}")
#                     if gitlab_target_type_str == "issue" and action_close_issue:
#                         try:
#                             issue_to_close = call_with_retry(f"fetch issue {created_gl_item.iid} for closing", gitlab_project.issues.get, created_gl_item.iid)
#                             if issue_to_close: 
#                                 issue_to_close.state_event = 'close'
#                                 call_with_retry(f"close issue {created_gl_item.iid}", issue_to_close.save)
#                                 logger.info(f"    SUCCESS: Closed GitLab Issue #{created_gl_item.iid}")
#                         except Exception as e_close: logger.warning(f"    Could not close GitLab Issue #{created_gl_item.iid}. Error: {e_close}")
#                     gitlab_item_for_comments = created_gl_item
#                     ado_id_to_gitlab[ado_work_item_id] = {'type': gitlab_target_type_str, 'id': created_gl_item.iid, 'gitlab_global_id': created_gl_item.id}
#                     save_mapping(ADO_GITLAB_MAP_FILE, ado_id_to_gitlab)
#                 else: 
#                     logger.error(f"  Failed to create GitLab {gitlab_target_type_str} for ADO #{ado_work_item_id} after retries or due to duplication.")
#                     continue 
#             except Exception as e_general_create:
#                 logger.error(f"  UNEXPECTED ERROR during item creation phase for ADO #{ado_work_item_id}.", exc_info=True)
#                 continue

#         if script_config.get('migrate_comments', False) and gitlab_item_for_comments:
#             logger.info(f"  Fetching comments for ADO #{ado_work_item_id} (GitLab {gitlab_item_type_for_comments} #{gitlab_item_for_comments.iid})...")
#             try:
#                 ado_comments_result = wit_client.get_comments(project=AZURE_PROJECT, work_item_id=ado_work_item_id, top=200, order="asc")
#                 ado_comments_list = ado_comments_result.comments if hasattr(ado_comments_result, 'comments') and ado_comments_result.comments else []
#                 if ado_comments_list:
#                     logger.info(f"  Found {len(ado_comments_list)} comments in ADO. Migrating...")
#                     ado_comments_list.sort(key=lambda c: c.created_date)
#                     for ado_comment in ado_comments_list:
#                         try:
#                             author_identity = ado_comment.created_by
#                             author_repr = get_ado_user_representation(author_identity, script_config)
#                             ts_dt = ado_comment.created_date
#                             if ts_dt.tzinfo is None: ts_dt_utc = ts_dt.replace(tzinfo=timezone.utc)
#                             else: ts_dt_utc = ts_dt.astimezone(timezone.utc)
#                             ts_str = ts_dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
#                             header = script_config.get('migrated_comment_header_format', "**Comment from ADO by {author} on {timestamp}:**\n\n").format(author=author_repr, timestamp=ts_str)
#                             note_body = f"{header}{basic_html_to_markdown(ado_comment.text)}"
#                             payload = {'body': note_body}
#                             try: payload['created_at'] = ts_dt_utc.isoformat()
#                             except: pass 
#                             action_desc_comment = f"add ADO comment {ado_comment.id} to GL {gitlab_item_type_for_comments} #{gitlab_item_for_comments.iid}"
#                             call_with_retry(action_desc_comment, gitlab_item_for_comments.notes.create, payload)
#                             logger.debug(f"    Successfully added ADO comment (ID: {ado_comment.id})")
#                         except Exception as e_comm: logger.warning(f"    Error adding ADO comment ID {ado_comment.id if ado_comment else 'N/A'}. Error: {e_comm}", exc_info=True)
#             except Exception as e_fetch_c: logger.error(f"  Failed to fetch/process comments for ADO #{ado_work_item_id}. Error: {e_fetch_c}", exc_info=True)

#     logger.info("--- Phase 2: Linking Parent/Child and Other Relations ---")
#     if not ado_work_item_refs: logger.info("No work items found, skipping linking phase.")
#     else:
#         for wi_ref_source in ado_work_item_refs:
#             source_ado_id = wi_ref_source.id
#             if source_ado_id not in ado_id_to_gitlab: continue
#             source_gitlab_info = ado_id_to_gitlab[source_ado_id]
#             logger.info(f"Processing links for source ADO #{source_ado_id} (GitLab {source_gitlab_info['type']} #{source_gitlab_info['id']})...")
#             try:
#                 ado_item_with_relations = wit_client.get_work_item(source_ado_id, expand="Relations")
#                 relations = getattr(ado_item_with_relations, "relations", None)
#                 if relations:
#                     for rel in relations:
#                         target_ado_id = -1 
#                         try:
#                             # --- Improved URL Parsing for Work Item Links ---
#                             rel_url_lower = getattr(rel, 'url', "").lower() # Safe access to url and lowercasing
#                             if not rel_url_lower or "/_apis/wit/workitems/" not in rel_url_lower:
#                                 logger.debug(f"  Skipping non-work item relation URL: '{getattr(rel, 'url', 'N/A')}' for source ADO #{source_ado_id}")
#                                 continue
                            
#                             target_ado_id_str = rel.url.split("/")[-1]
#                             if not target_ado_id_str.isdigit():
#                                 logger.warning(f"  Could not parse Target ADO ID from URL (non-integer suffix): {rel.url} for source ADO #{source_ado_id}")
#                                 continue
#                             target_ado_id = int(target_ado_id_str)
#                             # --- End of Improved URL Parsing ---

#                             ado_link_ref_name = rel.rel 
#                             ado_link_friendly_name = getattr(rel, 'attributes', {}).get('name', 'UnknownLinkType')
#                             logger.debug(f"  Found ADO link: Source ADO #{source_ado_id} --[{ado_link_friendly_name} ({ado_link_ref_name})]--> Target ADO #{target_ado_id}")
#                             if target_ado_id not in ado_id_to_gitlab:
#                                 logger.info(f"    Target ADO #{target_ado_id} for link from ADO #{source_ado_id} was not mapped. Skipping.")
#                                 continue
#                             target_gitlab_info = ado_id_to_gitlab[target_ado_id]
#                             is_hierarchical, parent_gl, child_gl = False, None, None
#                             if ado_link_ref_name == "System.LinkTypes.Hierarchy-Forward": 
#                                 parent_gl, child_gl, is_hierarchical = target_gitlab_info, source_gitlab_info, True
#                             elif ado_link_ref_name == "System.LinkTypes.Hierarchy-Reverse":
#                                 parent_gl, child_gl, is_hierarchical = source_gitlab_info, target_gitlab_info, True
                            
#                             if is_hierarchical:
#                                 action_desc_link = f"hierarchical link GL {child_gl['type']} #{child_gl['id']} to GL {parent_gl['type']} #{parent_gl['id']}"
#                                 if parent_gl['type'] == 'epic' and child_gl['type'] == 'issue':
#                                     retrieved_epic = call_with_retry(f"fetch epic {parent_gl['id']}", gitlab_group.epics.get, parent_gl['id'])
#                                     if retrieved_epic:
#                                         # Check if issue is already linked by fetching existing links (more robust)
#                                         # However, python-gitlab's add_issue might not error out if already linked, or error might be generic
#                                         # The call_with_retry will catch GitlabCreateError if it's a duplicate and log INFO.
#                                         if call_with_retry(action_desc_link, retrieved_epic.add_issue, child_gl['gitlab_global_id']) is not None:
#                                             logger.info(f"      SUCCESS: {action_desc_link}")
#                                 elif parent_gl['type'] == 'issue' and child_gl['type'] == 'issue':
#                                     parent_issue_gl = call_with_retry(f"fetch issue {parent_gl['id']}", gitlab_project.issues.get, parent_gl['id'])
#                                     if parent_issue_gl:
#                                         link_payload = {'target_project_id': gitlab_project.id, 'target_issue_iid': child_gl['id'], 'link_type': 'relates_to'}
#                                         if call_with_retry(action_desc_link, parent_issue_gl.links.create, link_payload) is not None:
#                                             logger.info(f"      SUCCESS: {action_desc_link} as 'relates_to'")
#                                 continue # Processed as hierarchical
                            
#                             mapped_gl_link_type = script_config.get('ado_to_gitlab_link_type_mapping', {}).get(ado_link_ref_name) or \
#                                                   script_config.get('default_gitlab_link_type')
#                             if mapped_gl_link_type and mapped_gl_link_type not in ["_parent_of_current_", "_child_of_current_"]:
#                                 if source_gitlab_info['type'] == 'issue' and target_gitlab_info['type'] == 'issue':
#                                     action_desc_generic_link = f"generic link GL Issue #{source_gitlab_info['id']} to #{target_gitlab_info['id']} as {mapped_gl_link_type}"
#                                     source_issue_gl = call_with_retry(f"fetch issue {source_gitlab_info['id']}", gitlab_project.issues.get, source_gitlab_info['id'])
#                                     if source_issue_gl:
#                                         link_payload = {'target_project_id': gitlab_project.id, 'target_issue_iid': target_gitlab_info['id'], 'link_type': mapped_gl_link_type}
#                                         if call_with_retry(action_desc_generic_link, source_issue_gl.links.create, link_payload) is not None:
#                                             logger.info(f"      SUCCESS: {action_desc_generic_link}")
#                                 else: logger.info(f"    Skipping generic link type '{mapped_gl_link_type}': Both items must be GitLab 'issues'.")
#                             elif ado_link_ref_name not in script_config.get('ado_to_gitlab_link_type_mapping', {}): # Check if it was explicitly ignored or just not mapped
#                                 if ado_link_ref_name not in script_config.get('ado_to_gitlab_link_type_mapping', {}) or \
#                                    script_config.get('ado_to_gitlab_link_type_mapping', {}).get(ado_link_ref_name) is not None: # Not explicitly set to null
#                                     logger.info(f"    ADO Link type '{ado_link_ref_name}' from ADO #{source_ado_id} to #{target_ado_id} is not mapped and no default applicable. Skipping.")
#                         except Exception as e_rel_proc: logger.warning(f"    Error processing relation for ADO source {source_ado_id} to target {target_ado_id}: {rel.url if rel else 'N/A'}. Error: {e_rel_proc}", exc_info=True)
#                 else: logger.debug(f"  No relations found for ADO source #{source_ado_id}.")
#             except Exception as e_outer_rel: logger.error(f"  Error retrieving relations for ADO source #{source_ado_id}. Error: {e_outer_rel}", exc_info=True)
#     logger.info("--- Migration Script Finished ---")

# if __name__ == '__main__':
#     main()
 