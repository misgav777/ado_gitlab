import logging
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication

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
        wiql_results_ado = wit_client.query_by_wiql(wiql_payload)
        if wiql_results_ado and hasattr(wiql_results_ado, 'work_items') and wiql_results_ado.work_items is not None:
            logger.info(f"Found {len(wiql_results_ado.work_items)} work item references in ADO.")
            return wiql_results_ado.work_items
        else:
            logger.info("No work item references found or unexpected query result structure from ADO.")
            return []
    except Exception as e:
        logger.critical(f"Failed to query work items from ADO. Error: {e}", exc_info=True)
        return [] # Return empty list on failure

def get_ado_work_item_details(wit_client, work_item_id, expand_relations=True):
    """Fetches full details for a single ADO work item."""
    try:
        expand_value = "Relations" if expand_relations else None
        return wit_client.get_work_item(work_item_id, expand=expand_value)
    except Exception as e:
        logger.error(f"Failed to get details for ADO work item #{work_item_id}. Error: {e}", exc_info=True)
        return None

def get_ado_work_item_comments(wit_client, azure_project_name, work_item_id, top=200, order="asc"):
    """Fetches comments for an ADO work item."""
    try:
        # ADO 'get_comments' can be paged. Using top=200 for now.
        # For >200 comments, pagination logic with continuationToken would be needed.
        ado_comments_result = wit_client.get_comments(project=azure_project_name, work_item_id=work_item_id, top=top, order=order)
        if hasattr(ado_comments_result, 'comments') and ado_comments_result.comments:
            return sorted(ado_comments_result.comments, key=lambda c: c.created_date) # Ensure chronological
        return []
    except Exception as e:
        logger.error(f"Failed to fetch comments for ADO work item #{work_item_id}. Error: {e}", exc_info=True)
        return []
