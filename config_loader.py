# ado_gitlab_migration/config_loader.py
import json
import os
import yaml
import logging

logger = logging.getLogger('ado_gitlab_migrator') # Get logger instance

# MIGRATION_CONFIG_FILE can remain global if it's not project-specific
MIGRATION_CONFIG_FILE = 'migration_config.yaml'
# ADO_GITLAB_MAP_FILE is no longer a global constant here, 
# it's constructed in main_migrator.py and passed to functions.

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
    """Loads the migration configuration from a YAML file."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                logger.info(f"Successfully loaded migration configuration from {filepath}")
                return config_data
        except yaml.YAMLError as e:
            logger.error(f"Could not parse YAML configuration file {filepath}: {e}", exc_info=True)
            return None # Indicate failure
        except Exception as e:
            logger.error(f"Could not load configuration file {filepath}", exc_info=True)
            return None
    else:
        logger.error(f"Migration configuration file {filepath} not found.")
        return None
