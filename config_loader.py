import json
import os
import yaml
import logging

logger = logging.getLogger('ado_gitlab_migrator') # Get logger instance

# MIGRATION_CONFIG_FILE can remain global if it's not project-specific
MIGRATION_CONFIG_FILE = 'migration_config.yaml'
# ADO_GITLAB_MAP_FILE is no longer a global constant here, 
# it's constructed in main_migrator.py and passed to functions.

def validate_migration_config(config):
    """Validates the migration configuration for required fields and proper structure."""
    required_fields = [
        'ado_to_gitlab_type',
        'default_gitlab_type',
        'ado_state_to_gitlab_labels'
    ]
    
    errors = []
    
    # Check required top-level fields
    for field in required_fields:
        if field not in config:
            errors.append(f"Missing required field: {field}")
    
    # Validate ADO to GitLab type mapping
    if 'ado_to_gitlab_type' in config:
        valid_gitlab_types = ['epic', 'issue']
        for ado_type, gitlab_type in config['ado_to_gitlab_type'].items():
            if gitlab_type not in valid_gitlab_types:
                errors.append(f"Invalid GitLab type '{gitlab_type}' for ADO type '{ado_type}'. Must be 'epic' or 'issue'")
    
    # Validate default GitLab type
    if 'default_gitlab_type' in config:
        if config['default_gitlab_type'] not in ['epic', 'issue']:
            errors.append(f"Invalid default_gitlab_type: {config['default_gitlab_type']}. Must be 'epic' or 'issue'")
    
    # Validate state mappings
    if 'ado_state_to_gitlab_labels' in config:
        valid_actions = ['_close_issue_', '_reopen_issue_']
        for state, mapping in config['ado_state_to_gitlab_labels'].items():
            if isinstance(mapping, dict):
                if 'action' in mapping and mapping['action'] not in valid_actions:
                    errors.append(f"Invalid action '{mapping['action']}' for state '{state}'")
    
    # Validate user mapping has default
    if 'user_mapping' in config and '_default_' not in config['user_mapping']:
        errors.append("user_mapping should include a '_default_' fallback user")
    
    # Validate area path handling strategy
    if 'area_path_handling_strategy' in config:
        valid_strategies = ['full_path', 'last_segment_only', 'all_segments', 'all_segments_hierarchical']
        if config['area_path_handling_strategy'] not in valid_strategies:
            errors.append(f"Invalid area_path_handling_strategy: {config['area_path_handling_strategy']}. Must be one of: {valid_strategies}")
    
    # Validate new label color strategy
    if 'new_label_color_strategy' in config:
        valid_color_strategies = ['random', 'fixed', 'default_gitlab']
        if config['new_label_color_strategy'] not in valid_color_strategies:
            errors.append(f"Invalid new_label_color_strategy: {config['new_label_color_strategy']}. Must be one of: {valid_color_strategies}")
    
    if errors:
        raise ValueError(f"Configuration validation failed:\n" + "\n".join(f"- {error}" for error in errors))
    
    logger.info("Configuration validation passed successfully")
    return True

def load_mapping(filepath): # filepath will be passed by main_migrator
    """Loads the ADO ID to GitLab ID mapping from a JSON file."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                mapping_str_keys = json.load(f)
                # Ensure ADO IDs (keys) are integers
                mapping_int_keys = {int(k): v for k, v in mapping_str_keys.items()}
                logger.debug(f"Successfully loaded and parsed mapping from {filepath}")
                return mapping_int_keys
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Mapping file {filepath} is corrupted or has invalid format ({e}). Starting with an empty map.")
            return {}
        except Exception as e:
            logger.error(f"Could not load mapping file {filepath}", exc_info=True)
            return {}
    logger.info(f"Mapping file {filepath} not found. Starting with an empty map.")
    return {}

def save_mapping(mapping_data, filepath): # filepath will be passed by main_migrator
    """Saves the ADO ID to GitLab ID mapping to a JSON file."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, indent=2)
        logger.debug(f"Successfully saved mapping to {filepath}")
    except Exception as e:
        logger.error(f"Could not save mapping file {filepath}", exc_info=True)

def load_migration_config(filepath=MIGRATION_CONFIG_FILE): # This is the function being called
    """Loads and validates the migration configuration from a YAML file."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                logger.info(f"Successfully loaded migration configuration from {filepath}")
                
                # Validate the configuration
                validate_migration_config(config_data)
                
                return config_data
        except yaml.YAMLError as e:
            logger.error(f"Could not parse YAML configuration file {filepath}: {e}", exc_info=True)
            return None # Indicate failure
        except ValueError as e:
            logger.error(f"Configuration validation failed for {filepath}: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Could not load configuration file {filepath}", exc_info=True)
            return None
    else:
        logger.error(f"Migration configuration file {filepath} not found.")
        return None