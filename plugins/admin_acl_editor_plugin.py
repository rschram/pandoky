# pandoky/plugins/admin_acl_editor_plugin.py

import os
import json
import re
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, g, current_app, session, abort
)
from werkzeug.security import generate_password_hash # For admin user creation
from functools import wraps
import sys

# --- Attempt to import from the main acl_plugin ---
ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY = False
try:
    from plugins.acl_plugin import ( 
        check_permission as main_acl_check_permission,
        PERMISSION_LEVELS as MAIN_PERMISSION_LEVELS,
        CONFIG_FILENAME as MAIN_CONFIG_FILENAME, # For admin users, site defaults
        GROUPS_FILENAME as MAIN_GROUPS_FILENAME, # For group definitions
        # GROUP_PERMISSIONS_FILENAME as MAIN_GROUP_PERMISSIONS_FILENAME, # If your acl_plugin uses this
        #ACL_RULES_FILENAME as MAIN_ACL_RULES_FILENAME # If your acl_plugin uses this
    )
    ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY = True
    PERMISSION_LEVELS = MAIN_PERMISSION_LEVELS
    CONFIG_FILENAME = MAIN_CONFIG_FILENAME 
    GROUPS_FILENAME = MAIN_GROUPS_FILENAME 
    # Ensure GROUP_PERMISSIONS_FILENAME is defined if used by this plugin's logic later
    GROUP_PERMISSIONS_FILENAME = getattr(sys.modules['plugins.acl_plugin'], 'GROUP_PERMISSIONS_FILENAME', "acl_group_permissions.json") # Default if not in acl_plugin
    #ACL_RULES_FILENAME = MAIN_ACL_RULES_FILENAME


except ImportError as e:
    print(f"AdminACLEditorPlugin: CRITICAL - Failed to import from acl_plugin: {e}. Admin functionality for ACL will be disabled.")
    PERMISSION_LEVELS = {"admin": 5, "read": 1, "none": 0, "edit": 2, "create": 3, "delete": 4} 
    CONFIG_FILENAME = "acl_config.json" 
    GROUPS_FILENAME = "acl_groups.json" 
    #ACL_RULES_FILENAME = "acl_rules.json" 
    GROUP_PERMISSIONS_FILENAME = "acl_group_permissions.json" # Fallback

    def main_acl_check_permission(app_instance, username, required_action, resource_path=None):
        if hasattr(app_instance, 'logger'):
            app_instance.logger.error("AdminACLEditorPlugin: Using fallback main_acl_check_permission - acl_plugin FAILED TO IMPORT.")
        return False


# --- Configuration for this Admin Editor Plugin ---
ADMIN_ACL_EDITOR_BLUEPRINT_NAME = 'admin_acl_editor_plugin'
# User data file configuration (should match auth_plugin.py) for admin user creation
AUTH_USERS_FILENAME = "auth_users.json" # From auth_plugin.py
AUTH_DEFAULT_HASH_METHOD = 'pbkdf2:sha256' # From auth_plugin.py


# --- Blueprint Definition ---
admin_acl_editor_bp = Blueprint(
    ADMIN_ACL_EDITOR_BLUEPRINT_NAME,
    __name__,
    template_folder='../templates/html/admin_acl', 
    url_prefix='/admin/acl' 
)

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
            app_instance.logger.error(f"AdminACLEditorPlugin: Error decoding JSON from {file_path}")
        except Exception as e:
            app_instance.logger.error(f"AdminACLEditorPlugin: Error loading {file_path}: {e}")
    return default_data

def save_json_data(app_instance, filename, data):
    file_path = get_data_file_path(app_instance, filename)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        app_instance.logger.info(f"AdminACLEditorPlugin: Data saved to {file_path}")
        return True
    except Exception as e:
        app_instance.logger.error(f"AdminACLEditorPlugin: Error saving data to {file_path}: {e}")
        return False

# --- Route Protection Helper ---
def admin_required_for_acl_editor(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        app_instance = getattr(g, 'app', current_app._get_current_object()) 

        if not ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY:
            app_instance.logger.error("AdminACLEditorPlugin: admin_required check failed - acl_plugin components FAILED TO IMPORT.")
            flash("Admin functionality for ACL is disabled because the main ACL system components are not available.", "error")
            abort(503) 

        current_user = getattr(g, 'current_user', None) 
        app_instance.logger.debug(f"AdminACLEditorPlugin: admin_required checking user '{current_user}' for 'admin_site'.")

        if not main_acl_check_permission(app_instance, current_user, "admin_site", resource_path="SITE_ADMIN_ACL_EDITOR"):
            app_instance.logger.warning(f"AdminACLEditorPlugin: Permission DENIED for user '{current_user}' to 'admin_site'.")
            flash("You do not have permission to access this admin area.", "error")
            if current_user is None:
                return redirect(url_for('auth_plugin.login_route', next=request.url))
            else:
                abort(403) 
        
        app_instance.logger.debug(f"AdminACLEditorPlugin: admin_required PASSED for user '{current_user}'")
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---
@admin_acl_editor_bp.route('/dashboard') # Changed from '/'
@admin_required_for_acl_editor
def dashboard():
    app_instance = g.app 
    config_data = load_json_data(app_instance, CONFIG_FILENAME)
    groups_data = load_json_data(app_instance, GROUPS_FILENAME)
    # Check if GROUP_PERMISSIONS_FILENAME is defined and used by the simple_acl_plugin
    # If your simple_acl_plugin only uses acl_rules.json for group permissions, adjust this
    group_permissions_data = {}
    if 'GROUP_PERMISSIONS_FILENAME' in globals() and GROUP_PERMISSIONS_FILENAME: # Check if constant is defined
        group_permissions_data = load_json_data(app_instance, GROUP_PERMISSIONS_FILENAME)

    return render_template(
        'dashboard.html', 
        title="ACL Editor Dashboard",
        config_data=config_data,
        groups_data=groups_data,
        group_permissions_data=group_permissions_data, # For simple ACL group perms
        permission_levels=PERMISSION_LEVELS
    )

@admin_acl_editor_bp.route('/config', methods=['GET', 'POST'])
@admin_required_for_acl_editor
def edit_config():
    app_instance = g.app
    
    if request.method == 'POST':
        try:
            admin_users_str = request.form.get('admin_users', '')
            default_anon_perm = request.form.get('default_anonymous', 'none')
            default_auth_perm = request.form.get('default_authenticated', 'none')

            admin_users = sorted(list(set([user.strip() for user in admin_users_str.split(',') if user.strip()])))
            
            if default_anon_perm not in PERMISSION_LEVELS or default_auth_perm not in PERMISSION_LEVELS:
                flash("Invalid permission level selected for defaults.", "error")
            else:
                current_config = load_json_data(app_instance, CONFIG_FILENAME)
                current_config['admin_users'] = admin_users
                current_config['default_permissions'] = {
                    'anonymous': default_anon_perm,
                    'authenticated': default_auth_perm
                }
                if save_json_data(app_instance, CONFIG_FILENAME, current_config):
                    flash("ACL site configuration saved successfully.", "success")
                else:
                    flash("Failed to save ACL site configuration.", "error")
                return redirect(url_for('.dashboard')) 
        except Exception as e:
            flash(f"Error processing form: {e}", "error")
            app_instance.logger.error(f"AdminACLEditorPlugin: Error saving ACL config: {e}", exc_info=True)

    current_config = load_json_data(app_instance, CONFIG_FILENAME)
    return render_template(
        'edit_config.html', 
        title="Edit ACL Site Configuration", 
        config_data=current_config,
        permission_levels_list=PERMISSION_LEVELS.keys()
    )

@admin_acl_editor_bp.route('/groups', methods=['GET', 'POST'])
@admin_required_for_acl_editor
def manage_groups():
    app_instance = g.app
    groups_data = load_json_data(app_instance, GROUPS_FILENAME, default_data={})

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == "add_group":
            new_group_name = request.form.get('new_group_name', '').strip()
            if not new_group_name:
                flash("Group name cannot be empty.", "error")
            elif not re.match(r"^[a-zA-Z0-9_-]+$", new_group_name):
                flash("Group name can only contain letters, numbers, underscores, and hyphens.", "error")
            elif new_group_name in groups_data or new_group_name in ["anonymous", "authenticated"]:
                flash(f"Group name '{new_group_name}' is reserved or already exists.", "error")
            else:
                groups_data[new_group_name] = [] 
                if save_json_data(app_instance, GROUPS_FILENAME, groups_data):
                    flash(f"Group '{new_group_name}' created successfully.", "success")
                else:
                    flash(f"Failed to create group '{new_group_name}'.", "error")
                return redirect(url_for('.manage_groups'))
        
        elif action == "delete_group":
            group_to_delete = request.form.get('group_to_delete', '').strip()
            if group_to_delete and group_to_delete in groups_data:
                # Remove from simple_acl_group_permissions.json if it exists and is used
                if 'GROUP_PERMISSIONS_FILENAME' in globals() and GROUP_PERMISSIONS_FILENAME:
                    group_permissions_data = load_json_data(app_instance, GROUP_PERMISSIONS_FILENAME)
                    if group_to_delete in group_permissions_data:
                        del group_permissions_data[group_to_delete]
                        save_json_data(app_instance, GROUP_PERMISSIONS_FILENAME, group_permissions_data)
                
                # Also check and remove from complex acl_rules.json if that file is being managed
                acl_rules = load_json_data(app_instance, ACL_RULES_FILENAME, default_data={})
                rules_modified = False
                if group_to_delete in acl_rules.get("global_permissions", {}).get("groups", {}):
                    del acl_rules["global_permissions"]["groups"][group_to_delete]
                    rules_modified = True
                for path_rule in acl_rules.get("path_permissions", {}).values():
                    if group_to_delete in path_rule.get("groups", {}):
                        del path_rule["groups"][group_to_delete]
                        rules_modified = True
                if rules_modified:
                    save_json_data(app_instance, ACL_RULES_FILENAME, acl_rules)


                del groups_data[group_to_delete]
                if save_json_data(app_instance, GROUPS_FILENAME, groups_data):
                    flash(f"Group '{group_to_delete}' deleted successfully.", "success")
                else:
                    flash(f"Failed to delete group '{group_to_delete}'.", "error")
            else:
                flash(f"Group '{group_to_delete}' not found for deletion.", "error")
            return redirect(url_for('.manage_groups'))

    return render_template('manage_groups.html', title="Manage User Groups", groups_data=groups_data) 

@admin_acl_editor_bp.route('/groups/edit/<group_name>', methods=['GET', 'POST'])
@admin_required_for_acl_editor
def edit_group_members(group_name):
    app_instance = g.app
    groups_data = load_json_data(app_instance, GROUPS_FILENAME, default_data={})

    if group_name not in groups_data:
        flash(f"Group '{group_name}' not found.", "error")
        return redirect(url_for('.manage_groups'))

    if request.method == 'POST':
        members_str = request.form.get('members', '')
        members_list = sorted(list(set([member.strip() for member in members_str.split(',') if member.strip()])))
        
        groups_data[group_name] = members_list
        
        if save_json_data(app_instance, GROUPS_FILENAME, groups_data):
            flash(f"Members of group '{group_name}' updated successfully.", "success")
        else:
            flash(f"Failed to update members for group '{group_name}'.", "error")
        return redirect(url_for('.manage_groups'))

    group_members = groups_data.get(group_name, [])
    return render_template('edit_group_members.html', 
                           title=f"Edit Members for Group: {group_name}", 
                           group_name=group_name, 
                           members=group_members)

@admin_acl_editor_bp.route('/group-permissions', methods=['GET', 'POST'])
@admin_required_for_acl_editor
def manage_group_permissions(): 
    app_instance = g.app
    # This route manages the GROUP_PERMISSIONS_FILENAME for the simple ACL model
    group_permissions_data = {}
    if 'GROUP_PERMISSIONS_FILENAME' in globals() and GROUP_PERMISSIONS_FILENAME:
        group_permissions_data = load_json_data(app_instance, GROUP_PERMISSIONS_FILENAME, default_data={})
    else:
        flash("Group permissions file configuration is missing. This section might not work as expected.", "warning")


    all_custom_groups = load_json_data(app_instance, GROUPS_FILENAME, default_data={}) 

    if request.method == 'POST':
        group_to_set = request.form.get('group_to_set')
        permission_level = request.form.get('permission_level')

        if not group_to_set:
            flash("Please select a group.", "error")
        elif group_to_set not in all_custom_groups: 
            flash(f"Group '{group_to_set}' does not exist.", "error")
        elif permission_level not in PERMISSION_LEVELS: 
            flash(f"Invalid permission level '{permission_level}'.", "error")
        elif 'GROUP_PERMISSIONS_FILENAME' not in globals() or not GROUP_PERMISSIONS_FILENAME:
             flash("Cannot save group permissions: configuration missing.", "error")
        else:
            group_permissions_data[group_to_set] = permission_level
            if save_json_data(app_instance, GROUP_PERMISSIONS_FILENAME, group_permissions_data):
                flash(f"Permission for group '{group_to_set}' set to '{permission_level}'.", "success")
            else:
                flash(f"Failed to set permission for group '{group_to_set}'.", "error")
            return redirect(url_for('.manage_group_permissions'))

    return render_template('manage_group_permissions.html', 
                           title="Manage Custom Group Permissions",
                           group_permissions_data=group_permissions_data,
                           all_groups_list=all_custom_groups.keys(), 
                           permission_levels_list=PERMISSION_LEVELS.keys())





@admin_acl_editor_bp.route('/tools/recalculate-tfidf', methods=['POST'])
@admin_required_for_acl_editor 
def trigger_recalculate_tfidf():
    app_instance = g.app 
    app_instance.logger.info("AdminACLEditorPlugin: Received request to recalculate all TF-IDF vectors.")
    
    if hasattr(app_instance, 'recalculate_all_tfidf') and callable(app_instance.recalculate_all_tfidf):
        try:
            app_instance.recalculate_all_tfidf() 
            flash("Full TF-IDF recalculation process initiated. Check server logs for progress.", "success")
        except Exception as e:
            app_instance.logger.error(f"AdminACLEditorPlugin: Error triggering TF-IDF recalculation: {e}", exc_info=True)
            flash(f"Error triggering TF-IDF recalculation: {e}", "error")
    else:
        app_instance.logger.error("AdminACLEditorPlugin: 'recalculate_all_tfidf' function not found on app instance. Is the fulltext_indexer plugin loaded correctly and registered its method?")
        flash("'recalculate_all_tfidf' function not available. Indexer plugin might not be loaded or exposed its function correctly.", "error")
        
    return redirect(url_for('.dashboard'))

# --- User Management Routes (Admin) ---
@admin_acl_editor_bp.route('/users', methods=['GET'])
@admin_required_for_acl_editor
def manage_users():
    app_instance = g.app
    auth_users_data = load_json_data(app_instance, AUTH_USERS_FILENAME, default_data={})
    users_display_list = []
    for username, data in auth_users_data.items():
        users_display_list.append({
            "username": username,
            "email": data.get("email", "N/A"),
            "is_verified": data.get("is_verified", False)
        })
    return render_template('manage_users.html', 
                           title="Manage Users", 
                           users=users_display_list)

@admin_acl_editor_bp.route('/users/add', methods=['POST'])
@admin_required_for_acl_editor
def add_user_admin():
    app_instance = g.app
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    is_verified_admin = request.form.get('is_verified') == 'on' 

    if not username or not password or not email:
        flash("Username, email, and password are required to add a user.", "error")
        return redirect(url_for('.manage_users'))
    
    if not username.isalnum(): 
        flash("Username must be alphanumeric.", "error")
        return redirect(url_for('.manage_users'))
    
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        flash("Invalid email format.", "error")
        return redirect(url_for('.manage_users'))

    auth_users_data = load_json_data(app_instance, AUTH_USERS_FILENAME, default_data={})
    if username in auth_users_data:
        flash(f"Username '{username}' already exists.", "error")
        return redirect(url_for('.manage_users'))
    for u_data in auth_users_data.values():
        if u_data.get('email') == email:
            flash(f"Email '{email}' is already in use.", "error")
            return redirect(url_for('.manage_users'))

    auth_users_data[username] = {
        "email": email,
        "password_hash": generate_password_hash(password, method=AUTH_DEFAULT_HASH_METHOD),
        "is_verified": is_verified_admin, 
        "verification_token": None, 
        "verification_token_expiry": None,
        "password_reset_token": None,
        "password_reset_token_expiry": None
    }
    if save_json_data(app_instance, AUTH_USERS_FILENAME, auth_users_data):
        flash(f"User '{username}' created successfully by admin.", "success")
        app_instance.logger.info(f"AdminACLEditorPlugin: Admin created user '{username}'. Verified: {is_verified_admin}")
    else:
        flash(f"Failed to create user '{username}'.", "error")
    
    return redirect(url_for('.manage_users'))

@admin_acl_editor_bp.route('/users/delete/<username_to_delete>', methods=['POST'])
@admin_required_for_acl_editor
def delete_user_admin(username_to_delete):
    app_instance = g.app
    
    current_admin_user = getattr(g, 'current_user', None)
    if username_to_delete == current_admin_user:
        flash("You cannot delete your own admin account.", "error")
        return redirect(url_for('.manage_users'))

    auth_users_data = load_json_data(app_instance, AUTH_USERS_FILENAME, default_data={})
    if username_to_delete in auth_users_data:
        del auth_users_data[username_to_delete]
        
        acl_groups_data = load_json_data(app_instance, GROUPS_FILENAME, default_data={})
        groups_modified = False
        for group_name, members in acl_groups_data.items():
            if username_to_delete in members:
                members.remove(username_to_delete)
                groups_modified = True
        if groups_modified:
            save_json_data(app_instance, GROUPS_FILENAME, acl_groups_data)

        acl_config_data = load_json_data(app_instance, CONFIG_FILENAME, default_data={"admin_users":[]})
        if username_to_delete in acl_config_data.get("admin_users", []):
            acl_config_data["admin_users"].remove(username_to_delete)
            save_json_data(app_instance, CONFIG_FILENAME, acl_config_data)
        
        # If using complex ACL rules, clean them too
        if 'ACL_RULES_FILENAME' in globals() and ACL_RULES_FILENAME:
            acl_rules_data = load_json_data(app_instance, ACL_RULES_FILENAME, default_data={"global_permissions":{}, "path_permissions":{}})
            rules_modified = False
            if username_to_delete in acl_rules_data.get("global_permissions",{}).get("users",{}):
                del acl_rules_data["global_permissions"]["users"][username_to_delete]
                rules_modified = True
            for path_rules in acl_rules_data.get("path_permissions", {}).values():
                if username_to_delete in path_rules.get("users",{}):
                    del path_rules["users"][username_to_delete]
                    rules_modified = True
            if rules_modified:
                 save_json_data(app_instance, ACL_RULES_FILENAME, acl_rules_data)


        if save_json_data(app_instance, AUTH_USERS_FILENAME, auth_users_data):
            flash(f"User '{username_to_delete}' and their associated ACL entries deleted successfully.", "success")
            app_instance.logger.info(f"AdminACLEditorPlugin: Admin deleted user '{username_to_delete}'.")
        else:
            flash(f"Failed to fully delete user '{username_to_delete}' from auth file.", "error")
    else:
        flash(f"User '{username_to_delete}' not found.", "error")
        
    return redirect(url_for('.manage_users'))


# --- Plugin Registration ---
def register(app_instance, register_hook_func): 
    @app_instance.before_request 
    def admin_acl_editor_before_request_setup(): 
        if request.blueprint == ADMIN_ACL_EDITOR_BLUEPRINT_NAME: 
            if not hasattr(g, 'app'): 
                g.app = app_instance 
            if not hasattr(g, 'current_user'): 
                g.current_user = session.get('current_user')
            app_instance.logger.debug(f"AdminACLEditorPlugin: before_request - g.app set, g.current_user='{g.get('current_user')}' for blueprint {request.blueprint}")

    if not ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY:
        app_instance.logger.error("AdminACLEditorPlugin: CRITICAL - Cannot register blueprint because acl_plugin components failed to import.")
        return

    app_instance.register_blueprint(admin_acl_editor_bp) 
    app_instance.logger.info(f"ACL Editor plugin registered with routes at {admin_acl_editor_bp.url_prefix}.")

