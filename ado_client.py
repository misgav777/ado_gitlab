# ado_gitlab_migration/ado_client.py
import logging
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
# Import specific exception if needed, or rely on general Exception
# from azure.devops.exceptions import AzureDevOpsServiceError

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
    
    # Explicitly put the project name into the WIQL query string.
    wiql_query_string = f"SELECT {', '.join(fields_to_select)} FROM WorkItems WHERE [System.TeamProject] = '{azure_project_name}'"
    wiql_payload = {'query': wiql_query_string}
    logger.debug(f"Executing WIQL query: {wiql_query_string}")
    
    try:
        wiql_results_ado = wit_client.query_by_wiql(wiql_payload) # Pass payload as first positional argument
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
        expand_value = "Relations" if expand_relations else None
        # Ensure work_item_id is an int if your SDK version expects it strictly
        # The `project` parameter for get_work_item is usually not needed if the ID is global.
        return wit_client.get_work_item(id=int(work_item_id), expand=expand_value) 
    except Exception as e:
        logger.error(f"Failed to get details for ADO work item #{work_item_id}. Error: {e}", exc_info=True)
        return None

def get_ado_work_item_comments(wit_client, azure_project_name, work_item_id, top=200, order="asc"):
    """Fetches comments for an ADO work item."""
    try:
        # The project parameter IS typically required for get_comments by the SDK
        ado_comments_result = wit_client.get_comments(project=azure_project_name, work_item_id=int(work_item_id), top=top, order=order)
        if hasattr(ado_comments_result, 'comments') and ado_comments_result.comments:
            return sorted(ado_comments_result.comments, key=lambda c: c.created_date) 
        return []
    except Exception as e:
        logger.error(f"Failed to fetch comments for ADO work item #{work_item_id}. Error: {e}", exc_info=True)
        return []

# --- THIS FUNCTION WAS MISSING FROM THE UPLOADED ado_client.py ---
def get_ado_classification_node_details(wit_client, project_name, structure_type, path_str, depth=0):
    """
    Fetches details for a specific classification node (Iteration or Area).
    :param wit_client: The WorkItemTrackingClient.
    :param project_name: The name or ID of the project.
    :param structure_type: Either 'iterations' or 'areas'.
    :param path_str: The full path string of the node (e.g., "ProjectName\\Iteration\\Sprint 1").
                     It will be split by '\\' and the root project name removed if present.
    :param depth: The depth to retrieve (0 for the node itself, 1 for children, etc.).
    :return: The classification node object or None if not found or error.
    """
    path_segments = path_str.split('\\')
    effective_path = path_str # Default to full path if project name not found at start

    # Check if the first segment matches the project name (case-insensitive) and remove it
    if path_segments and path_segments[0].lower() == project_name.lower():
        effective_path = "\\".join(path_segments[1:])
        if not effective_path and len(path_segments) > 1 : 
             if not effective_path: 
                 logger.warning(f"Path '{path_str}' reduced to empty effective_path after stripping project. This might be the root node. API might need path='{structure_type}'.")
                 return None 
        elif not effective_path and len(path_segments) == 1: 
            logger.warning(f"Cannot fetch classification node for path '{path_str}' as it likely refers to the project root, not a specific node under '{structure_type}'.")
            return None

    if not effective_path.strip(): # If path is empty or only whitespace after processing
        logger.warning(f"Effective path for classification node is empty or whitespace for original path '{path_str}'. Cannot fetch node.")
        return None

    logger.debug(f"Fetching ADO classification node: Project='{project_name}', Type='{structure_type}', Effective Path='{effective_path}', Depth={depth}")
    try:
        node = wit_client.get_classification_node(
            project=project_name,
            structure_group=structure_type, 
            path=effective_path,            
            depth=depth                     
        )
        logger.debug(f"Successfully fetched classification node for original path '{path_str}'. Node Name: {getattr(node, 'name', 'N/A')}, Attributes: {getattr(node, 'attributes', None)}")
        return node
    except Exception as e:
        logger.error(f"Failed to get classification node for Project='{project_name}', Type='{structure_type}', Path='{effective_path}'. Error: {e}", exc_info=True)
        return None
