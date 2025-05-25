# main_migrator.py - Core Migration Engine

The `main_migrator.py` file serves as the orchestration layer and central execution point for the migration process. It coordinates the entire workflow from fetching ADO work items to creating GitLab entities and establishing relationships.

## Key Functions

### `main()`

The entry point that orchestrates the entire migration process. It performs these key steps:

1. **Setup and Initialization**
   - Initializes the database connection
   - Loads configuration from YAML
   - Establishes connections to ADO and GitLab
   - Sets up logging

2. **Work Item Discovery**
   - Queries ADO for work items to migrate
   - Batches requests to optimize API usage

3. **Primary Migration Loop**
   - Processes each work item to create GitLab issues or epics
   - Applies field mappings based on configuration
   - Records mappings in database for tracking

4. **Relationship Processing**
   - In a second phase, processes all relationships between items
   - Establishes parent/child relationships in GitLab
   - Maps ADO link types to GitLab link types

### `process_images_parallel()`

Handles parallel processing of images found in work items:

```python
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
```

### `batch_create_gitlab_items()`

Creates multiple GitLab items in parallel with rate limiting:

```python
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
```

### `save_checkpoint()` and `load_checkpoint()`

Manages checkpoint state for resumable migrations:

```python
def save_checkpoint(completed_ids, total_count, db_handler=None):
    checkpoint = {
        'completed_ids': completed_ids,
        'total_count': total_count,
        'timestamp': datetime.now().isoformat(),
        'completion_rate': len(completed_ids) / total_count * 100 if total_count > 0 else 0
    }
    with open('migration_checkpoint.json', 'w') as f:
        json.dump(checkpoint, f, indent=2)
    
    # Update database migration state if available
    if db_handler:
        db_handler.update_migration_status(
            status='in_progress',
            processed=len(completed_ids),
            failed=0
        )
```

## Key Processing Phases

### Phase 1: Creating Epics and Issues

This phase handles the creation of GitLab entities from ADO work items:

1. For each ADO work item:
   - Determine the target GitLab entity type (issue or epic)
   - Create the description with metadata footer
   - Apply labels based on ADO state, priority, area path
   - Set milestone based on ADO iteration path
   - Create GitLab entity and store mapping
   - Migrate comments if configured

### Phase 2: Linking Parent/Child and Other Relations

After all items are created, this phase establishes relationships:

1. For each ADO work item with relations:
   - Store all relationships in the database first
   - Process each relationship based on type
   - Map hierarchical relations (parent/child)
   - Map other relation types based on configuration
   - Update relationship status in database

## Error Handling

The script includes robust error handling throughout:

1. **Batch Processing Recovery**
   - Individual failures don't stop the entire migration
   - Records failures in database for later retry

2. **Exception Handling**
   - Wraps key operations in try/except blocks
   - Provides detailed logging for troubleshooting
   - Updates database state on failure

3. **Global Exception Handler**
   - Catches unhandled exceptions in main function
   - Updates database migration state on catastrophic failure