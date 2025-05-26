# ado_gitlab_migration/ado_client.py
import logging
import requests
import base64
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
# from azure.devops.exceptions import AzureDevOpsServiceError # For more specific error handling if needed

logger = logging.getLogger('ado_gitlab_migrator')

def init_ado_connection(org_url, pat):
    """Initializes and returns Azure DevOps connection and clients."""
    logger.info(f"Connecting to Azure DevOps organization: {org_url}...")
    try:
        credentials = BasicAuthentication('', pat)
        connection = Connection(base_url=org_url, creds=credentials)
        wit_client = connection.clients.get_work_item_tracking_client()
        core_client = connection.clients.get_core_client()
        logger.info(f"Azure DevOps connection successful to organization: {org_url}")
        return connection, wit_client, core_client
    except Exception as e:
        logger.critical(f"Azure DevOps connection failed. Error: {e}", exc_info=True)
        return None, None, None

def query_ado_work_item_refs(wit_client, azure_project_name, fields_to_select):
    """Queries ADO for work item references."""
    logger.info(f"Querying work items from ADO project: {azure_project_name}...")
    
    required_id_field = "[System.Id]"
    # Ensure System.Id is always selected for batch fetching later.
    # Make the check case-insensitive for the field list.
    if not any(field.lower() == required_id_field.lower() for field in fields_to_select):
        fields_to_select.append(required_id_field)
        logger.debug(f"Added {required_id_field} to WIQL fields as it's required.")

    wiql_query_string = f"SELECT {', '.join(fields_to_select)} FROM WorkItems WHERE [System.TeamProject] = @project"
    # Use @project parameter for safety, though direct string injection is common for project name in WIQL
    wiql_payload = {'query': wiql_query_string}
    # If using @project, you'd pass it in the context for the query_by_wiql call,
    # but the Python SDK often handles project context implicitly or via a project param in the client method.
    # For simplicity, if your direct string injection of azure_project_name worked, we can keep it.
    # Let's stick to your working direct injection for now:
    wiql_query_string = f"SELECT {', '.join(fields_to_select)} FROM WorkItems WHERE [System.TeamProject] = '{azure_project_name}'"
    wiql_payload = {'query': wiql_query_string}

    logger.debug(f"Executing WIQL query: {wiql_query_string}")
    
    try:
        wiql_results_ado = wit_client.query_by_wiql(wiql_payload) 
        if wiql_results_ado and hasattr(wiql_results_ado, 'work_items') and wiql_results_ado.work_items is not None:
            logger.info(f"Found {len(wiql_results_ado.work_items)} work item references in ADO.")
            return wiql_results_ado.work_items
        else:
            logger.info("No work item references found or unexpected query result structure from ADO.")
            return []
    except Exception as e:
        logger.critical(f"Failed to query work items from ADO. Error: {e}", exc_info=True)
        return [] 

def get_ado_work_item_details(wit_client, work_item_id, expand_relations=True):
    """Fetches full details for a single ADO work item."""
    try:
        expand_value = "$Relations" if expand_relations else "$None" # ADO REST API often uses $ prefix for expand options
        # The Python SDK might abstract this to "Relations" or "None" (string)
        # Let's try with the SDK's typical string values first.
        expand_value_sdk = "Relations" if expand_relations else "None"
        
        return wit_client.get_work_item(id=int(work_item_id), expand=expand_value_sdk) 
    except Exception as e:
        logger.error(f"Failed to get details for ADO work item #{work_item_id}. Error: {e}", exc_info=True)
        return None

def get_ado_work_items_batch(wit_client, work_item_ids_list, project_name=None, fields=None, expand_relations=True, error_policy="omit"):
    """
    Fetches details for a batch of ADO work items using get_work_items.
    """
    if not work_item_ids_list:
        return []
    
    logger.info(f"Batch fetching details for {len(work_item_ids_list)} ADO work items...")
    
    # API expects string "None", "Relations", "All", etc. for expand.
    expand_value_sdk = "Relations" if expand_relations else "None"
    ids_as_int = [int(id_val) for id_val in work_item_ids_list]

    # Parameters for the SDK call
    sdk_params = {
        'ids': ids_as_int,
        'project': project_name, # Pass project if required by your SDK version/setup
        'expand': expand_value_sdk,
        'error_policy': error_policy 
    }

    # CRITICAL FIX: If expand is "Relations" (or anything other than "None"),
    # do not pass the 'fields' parameter, as they conflict.
    if expand_relations: # Equivalent to expand_value_sdk == "Relations" or "All"
        logger.debug(f"Fetching batch with expand='{expand_value_sdk}'. 'fields' parameter will be omitted.")
    else: # Only include 'fields' if not expanding relations (or expanding "None")
        if fields:
            sdk_params['fields'] = fields
        else:
            # If no specific fields and not expanding, it fetches default fields.
            # No need to explicitly pass fields=None if the SDK handles it.
            pass


    try:
        work_items_details_list = wit_client.get_work_items(**sdk_params)
        
        fetched_items = [item for item in work_items_details_list if item is not None]
        logger.info(f"Successfully fetched details for {len(fetched_items)} out of {len(work_item_ids_list)} work items in batch.")
        return fetched_items
    except TypeError as te: 
        logger.error(f"TypeError calling get_work_items. This might indicate an SDK version mismatch or incorrect parameters. Error: {te}", exc_info=True)
        logger.error(f"Parameters passed to SDK (effective): {sdk_params}")
        # Fallback attempt (less likely to be needed if the above TypeError is due to expand/fields conflict)
        try:
            logger.info("Attempting fallback: calling get_work_items with ids as first positional argument (if TypeError was related to keywords)...")
            # This specific fallback might not help with expand/fields conflict, but good to have for general signature issues.
            positional_ids_params = {k: v for k, v in sdk_params.items() if k != 'ids'}
            work_items_details_list = wit_client.get_work_items(
                ids_as_int, 
                **positional_ids_params
            )
            fetched_items = [item for item in work_items_details_list if item is not None]
            logger.info(f"Fallback successful: Fetched details for {len(fetched_items)} work items.")
            return fetched_items
        except Exception as fallback_e:
            logger.error(f"Fallback attempt also failed. Error: {fallback_e}", exc_info=True)
            return []

    except Exception as e: # Catch other exceptions like AzureDevOpsServiceError
        logger.error(f"Failed to batch fetch ADO work items. IDs: {work_item_ids_list[:10]}... Error: {e}", exc_info=True)
        return []


def get_ado_work_item_comments(wit_client, azure_project_name, work_item_id, top=200, order="asc"):
    """Fetches comments for an ADO work item using direct REST API call.
    Since the Azure DevOps Python SDK doesn't support comments API directly,
    we use the requests library to call the REST API.
    """
    try:
        # Get organization URL from the client's connection
        org_url = wit_client._client.config.base_url
        
        # This is a hack to find org_url, based on how Azure DevOps SDKs URL format is
        # Example: https://dev.azure.com/org_name
        # or: https://org_name.visualstudio.com
        if not org_url.endswith('/'): 
            org_url += '/'
        
        # Build the API URL
        # Documentation: https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/comments/list?view=azure-devops-rest-7.0
        url = f"{org_url}{azure_project_name}/_apis/wit/workitems/{work_item_id}/comments"
        
        # Add query parameters
        params = {
            'api-version': '7.0-preview',  # Using API version 7.0-preview which supports comments
            '$top': top,
            'order': order
        }
        
        # Get PAT from connection credentials
        # The credential is stored as ':PAT' in the BasicAuthentication object
        auth_value = wit_client._client.config.credentials.password
        
        # Create auth header with PAT
        auth_header = f"Basic {base64.b64encode(f':{auth_value}'.encode()).decode()}"
        headers = {
            'Authorization': auth_header,
            'Content-Type': 'application/json'
        }
        
        # Make the REST call
        response = requests.get(url, params=params, headers=headers)
        
        # Process the response
        if response.status_code == 200:
            comments_data = response.json()
            if 'comments' in comments_data and comments_data['comments']:
                # Convert to objects with needed attributes for compatibility
                comment_objects = []
                for comment in comments_data['comments']:
                    # Create a simple object to match the expected structure
                    class CommentObj:
                        pass
                    
                    c = CommentObj()
                    c.id = comment.get('id')
                    c.text = comment.get('text', '')
                    c.created_date = comment.get('createdDate')
                    
                    # Add created_by information if available
                    if 'createdBy' in comment:
                        class IdentityRef:
                            pass
                        
                        identity = IdentityRef()
                        identity.display_name = comment['createdBy'].get('displayName', '')
                        identity.unique_name = comment['createdBy'].get('uniqueName', '')
                        identity.id = comment['createdBy'].get('id', '')
                        c.created_by = identity
                    
                    comment_objects.append(c)
                
                return sorted(comment_objects, key=lambda c: c.created_date)
            
        # If we get here, no comments were found or there was an error
        if response.status_code != 200:
            logger.warning(f"Failed to fetch comments for ADO #{work_item_id}. Status code: {response.status_code}, Response: {response.text}")
        else:
            logger.info(f"No comments found for work item #{work_item_id}")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch comments for ADO work item #{work_item_id}. Error: {e}", exc_info=True)
        return []

def get_ado_classification_node_details(wit_client, project_name, structure_type, path_str, depth=0):
    """
    Fetches details for a specific classification node (Iteration or Area).
    """
    path_segments = path_str.split('\\')
    effective_path = path_str 

    if path_segments and project_name and path_segments[0].lower() == project_name.lower():
        effective_path = "\\".join(path_segments[1:])
        if not effective_path and len(path_segments) == 1 : 
             logger.debug(f"Path '{path_str}' reduced to empty effective_path for project '{project_name}'. This implies the root of '{structure_type}'. Fetching this specific node might not be intended or supported directly via this path method for root.")
             # For fetching the root node itself, the path might need to be empty or just the structure_type.
             # However, if the original path was just the project name, it's unlikely to be a valid iteration/area node path.
             return None 

    if not effective_path.strip(): 
        logger.debug(f"Effective path for classification node is empty for original path '{path_str}'. This usually means it's the project root for '{structure_type}'.")
        # If you need to list all top-level iterations/areas, use get_classification_nodes with no path or a shallow depth.
        # This function is for getting a *specific* named node.
        return None

    logger.debug(f"Fetching ADO classification node: Project='{project_name}', Type='{structure_type}', Effective Path='{effective_path}', Depth={depth}")
    try:
        node = wit_client.get_classification_node(
            project=project_name,
            structure_group=structure_type, 
            path=effective_path,            
            depth=depth                     
        )
        logger.debug(f"Successfully fetched classification node for original path '{path_str}'. Node Name: {getattr(node, 'name', 'N/A')}")
        return node
    except Exception as e:
        logger.error(f"Failed to get classification node for Project='{project_name}', Type='{structure_type}', Path='{effective_path}'. Error: {e}", exc_info=True)
        return None
# ```

# **Explanation of the fix in `get_ado_work_items_batch`:**

# ```python
#     # ...
#     sdk_params = {
#         'ids': ids_as_int,
#         'project': project_name,
#         'expand': expand_value_sdk,
#         'error_policy': error_policy 
#     }

#     if expand_relations: # If expand_value_sdk is "Relations" or "All"
#         logger.debug(f"Fetching batch with expand='{expand_value_sdk}'. 'fields' parameter will be omitted.")
#         # No 'fields' key is added to sdk_params if expanding relations
#     else: 
#         if fields:
#             sdk_params['fields'] = fields
    
#     try:
#         # The **sdk_params unpacks only the relevant parameters based on the condition above
#         work_items_details_list = wit_client.get_work_items(**sdk_params) 
#     # ...
# ```

# When `expand_relations` is `True`, the `fields` key will not be added to the `sdk_params` dictionary that gets unpacked into the `wit_client.get_work_items()` call. This should resolve the `AzureDevOpsServiceError: The expand parameter can not be used with the fields parameter.`

# **Next Steps:**

# 1.  Replace your `ado_client.py` with the content above.
# 2.  Ensure that in `main_migrator.py`, the call to `get_ado_work_items_batch` for Phase 2 (relation fetching) correctly passes `expand_relations=True` and omits or passes `None` for the `fields` argument if you were explicitly passing it there. The `ado_client.py` change will handle omitting `fields` internally when `expand_relations` is true.

#     Your current call in `main_migrator.py` for Phase 2 is:
#     ```python
#                 items_with_relations_batch = ado_client.get_ado_work_items_batch(
#                     ado_wit_client,
#                     id_chunk_for_relations,
#                     project_name=AZURE_PROJECT, 
#                     fields=["System.Id", "System.Links.LinkType"], # This 'fields' will now be conditionally omitted by the client
#                     expand_relations=True, 
#                     error_policy="omit"
#                 )
#     ```
#     With the updated `ado_client.py`, the `fields` argument `["System.Id", "System.Links.LinkType"]` will be ignored by `get_ado_work_items_batch` when `expand_relations=True`. This is the desired behavior to fix the error. The API should return IDs and Links by default when expanding relations.

# 3.  Run the script again and check the logs.

# Let me know the outco