# pandoky/plugins/acl_plugin.py

import os
import json
from flask import g, flash, redirect, url_for, request, session, abort # Added request, session, abort
from functools import wraps

# --- Configuration ---
CONFIG_FILENAME = "acl_config.json"  # Stores admin_users, default_permissions
GROUPS_FILENAME = "acl_groups.json"  # Stores user-to-group memberships for custom groups
GROUP_PERMISSIONS_FILENAME = "acl_group_permissions.json" # Stores permissions for custom groups

# --- Permission Levels & Actions ---
# These should be consistent across your application
PERMISSION_LEVELS = {
    "none": 0,
    "read": 1,
    "edit": 2,
    "create": 3,
    "delete": 4,
    "admin": 5
}

ACTIONS_TO_REQUIRED_LEVEL = {
    "view_page": PERMISSION_LEVELS["read"],
    "edit_page": PERMISSION_LEVELS["edit"],
    "create_page": PERMISSION_LEVELS["create"],
    "save_page_new": PERMISSION_LEVELS["create"],
    "save_page_existing": PERMISSION_LEVELS["edit"],
    "delete_page": PERMISSION_LEVELS["delete"],
    "admin_site": PERMISSION_LEVELS["admin"] # For accessing admin interfaces
}

# --- Helper Functions for Data File Management ---
def get_data_file_path(app_instance, filename):
    data_dir = app_instance.config.get('DATA_DIR', os.path.join(app_instance.root_path, 'data'))
    return os.path.join(data_dir, filename)

def load_json_data(app_instance, filename, default_data=None):
    if default_data is None: default_data = {}
    file_path = get_data_file_path(app_instance, filename)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            app_instance.logger.error(f"ACLPlugin: Error decoding JSON from {file_path}")
        except Exception as e:
            app_instance.logger.error(f"ACLPlugin: Error loading {file_path}: {e}")
    return default_data

def save_json_data(app_instance, filename, data):
    file_path = get_data_file_path(app_instance, filename)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        app_instance.logger.info(f"ACLPlugin: Data saved to {file_path}")
    except Exception as e:
        app_instance.logger.error(f"ACLPlugin: Error saving data to {file_path}: {e}")

# --- Core Permission Checking Logic ---
def get_user_effective_permission_level(app_instance, username):
    """
    Determines the highest permission level for a user based on their group memberships.
    """
    config = load_json_data(app_instance, CONFIG_FILENAME,
                            default_data={"admin_users": [], 
                                          "default_permissions": {"anonymous": "read", "authenticated": "read"}})
    groups_data = load_json_data(app_instance, GROUPS_FILENAME, default_data={})
    group_permissions = load_json_data(app_instance, GROUP_PERMISSIONS_FILENAME, default_data={})

    # 1. Super Admin check (overrides everything)
    if username and username in config.get("admin_users", []):
        return PERMISSION_LEVELS["admin"]

    user_groups = set()
    if username:
        user_groups.add("authenticated") # All logged-in users are in this implicit group
        for group_name, members in groups_data.items():
            if username in members:
                user_groups.add(group_name)
    else:
        user_groups.add("anonymous") # Non-logged-in users

    max_level = PERMISSION_LEVELS["none"]

    # Check permissions from default "anonymous" or "authenticated" groups
    if "anonymous" in user_groups:
        level_str = config.get("default_permissions", {}).get("anonymous", "none")
        max_level = max(max_level, PERMISSION_LEVELS.get(level_str, PERMISSION_LEVELS["none"]))
    
    if "authenticated" in user_groups:
        level_str = config.get("default_permissions", {}).get("authenticated", "none")
        max_level = max(max_level, PERMISSION_LEVELS.get(level_str, PERMISSION_LEVELS["none"]))

    # Check permissions from custom groups
    for group in user_groups:
        if group in group_permissions: # Check custom group permissions
            level_str = group_permissions[group]
            max_level = max(max_level, PERMISSION_LEVELS.get(level_str, PERMISSION_LEVELS["none"]))
            
    return max_level

def check_permission(app_instance, username, required_action, resource_path=None): # resource_path is ignored in simple ACL
    """Checks if a user has permission for a specific action (globally)."""
    # In this simple model, resource_path is not used for permission checking itself,
    # but might be logged or used by hooks for context.
    required_level_value = ACTIONS_TO_REQUIRED_LEVEL.get(required_action, PERMISSION_LEVELS["admin"] + 1)
    user_level_value = get_user_effective_permission_level(app_instance, username)
    
    allowed = user_level_value >= required_level_value
    app_instance.logger.debug(
        f"ACL Check: User '{username}', Action '{required_action}' (req_level: {required_level_value}), "
        f"UserLevel: {user_level_value}. Allowed: {allowed}"
    )
    return allowed

# --- Hook Implementations ---
# These hooks will be registered with the main app.
# They need access to the app_instance, which will be provided via functools.partial or lambda in register()

def hook_before_page_access(page_name_slug, page_file_path, app_context):
    """Hook for `before_page_file_access`. Raises PermissionError if view denied."""
    current_user = g.get('current_user', None) 
    if not check_permission(app_context, current_user, "view_page", page_name_slug): # Pass page_name_slug for logging
        app_context.logger.warning(f"ACL: Access denied for user '{current_user}' to view page '{page_name_slug}'.")
        raise PermissionError(f"You do not have permission to view the page '{page_name_slug}'.")
    return page_name_slug # Must return the (potentially modified) first arg

def hook_before_page_save(raw_content, page_name, app_context):
    current_user = g.get('current_user', None)
    pages_dir = app_context.config.get('PAGES_DIR', os.path.join(app_context.root_path, 'data', 'pages'))
    page_file_path = os.path.join(pages_dir, page_name + '.md') 
    
    action = "save_page_new" if not os.path.exists(page_file_path) else "save_page_existing"
    
    if not check_permission(app_context, current_user, action, page_name):
        app_context.logger.warning(f"ACL: User '{current_user}' denied to '{action}' for page '{page_name}'.")
        raise PermissionError(f"You do not have permission to save this page ({page_name}).")
    return raw_content 

def hook_before_page_delete(cancel_default_action, page_name, file_path, app_context):
    current_user = g.get('current_user', None)
    if not check_permission(app_context, current_user, "delete_page", page_name):
        app_context.logger.warning(f"ACL: User '{current_user}' denied to delete page '{page_name}'.")
        flash(f"You do not have permission to delete this page ({page_name}).", "error")
        return True # Return True to cancel the delete operation
    return cancel_default_action # False, allow delete

# --- Plugin Registration ---
def register(app_instance, register_hook_func):
    """Registers the ACL plugin."""
    
    # Ensure g.current_user is set from session for every request
    # This is crucial for hooks and checks that rely on g.current_user
    @app_instance.before_request
    def acl_load_user_to_g():
        g.current_user = session.get('current_user') # From auth_plugin

    # Wrap hook functions to pass app_instance as app_context
    def _hook_before_page_access(page_name_slug, page_file_path, **kwargs):
        return hook_before_page_access(page_name_slug, page_file_path, app_context=kwargs.get('app_context', app_instance))
    
    def _hook_before_page_save(raw_content, page_name, **kwargs):
        return hook_before_page_save(raw_content, page_name, app_context=kwargs.get('app_context', app_instance))
    
    def _hook_before_page_delete(cancel_default_action, page_name, file_path, **kwargs):
        return hook_before_page_delete(cancel_default_action, page_name, file_path, app_context=kwargs.get('app_context', app_instance))

    register_hook_func('before_page_file_access', _hook_before_page_access)
    register_hook_func('before_page_save', _hook_before_page_save)
    register_hook_func('before_page_delete', _hook_before_page_delete)

    # Make check_permission available to templates as a global function
    def template_check_permission_wrapper(action, resource_path=None): # resource_path ignored by simple ACL
        return check_permission(app_instance, g.get('current_user'), action, resource_path)
    app_instance.jinja_env.globals['acl_check_permission'] = template_check_permission_wrapper
    app_instance.logger.info("ACLPlugin: Registered 'acl_check_permission' as a global for templates.")

    # Initialize data files if they don't exist
    default_config = {
        "admin_users": ["admin"], # Default admin user
        "default_permissions": { 
            "anonymous": "read",  # Default for non-logged-in users
            "authenticated": "read" # Default for logged-in users (can be overridden by custom groups)
        }
    }
    default_groups = {"editors": [], "another_group": []} # Example custom groups
    default_group_permissions = { # Permissions for custom groups
        "editors": "edit",
        "another_group": "read"
    }

    for filename, default_content in [
        (CONFIG_FILENAME, default_config),
        (GROUPS_FILENAME, default_groups),
        (GROUP_PERMISSIONS_FILENAME, default_group_permissions)
    ]:
        file_path = get_data_file_path(app_instance, filename)
        if not os.path.exists(file_path):
            app_instance.logger.info(f"ACLPlugin: Data file '{filename}' not found. Creating with defaults.")
            save_json_data(app_instance, filename, default_content)
    
    app_instance.logger.info("ACL plugin registered and hooks set.")

