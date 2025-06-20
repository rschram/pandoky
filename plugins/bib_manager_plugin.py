# pandoky/plugins/bib_manager_plugin.py

import os
import json
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, g, current_app, session, abort
)
from werkzeug.utils import secure_filename
from functools import wraps
import sys

# --- Attempt to import from the main acl_plugin ---
ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY = False
try:
    # This should point to your active ACL logic plugin (e.g., acl_plugin.py or simple_acl_plugin.py)
    from plugins.acl_plugin import ( 
        check_permission as main_acl_check_permission,
        PERMISSION_LEVELS as MAIN_PERMISSION_LEVELS
    )
    ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY = True
    PERMISSION_LEVELS = MAIN_PERMISSION_LEVELS # Use imported levels
except ImportError as e:
    # Fallback if the primary ACL plugin isn't found or has issues
    print(f"BibManagerPlugin: WARNING - Could not import from primary acl_plugin: {e}. Using fallbacks for admin check. Ensure acl_plugin.py is correct.")
    PERMISSION_LEVELS = {"admin": 5} 
    def main_acl_check_permission(app_instance, username, required_action, resource_path=None):
        if hasattr(app_instance, 'logger'): # Check if app_instance is a Flask app with a logger
            app_instance.logger.error("BibManagerPlugin: Using fallback main_acl_check_permission - acl_plugin FAILED TO IMPORT or is misconfigured.")
        return False # Default to deny for safety

# --- Configuration ---
BIB_MANAGER_BLUEPRINT_NAME = 'bib_manager_plugin'
ALLOWED_EXTENSIONS = {'bib', 'json', 'yaml', 'yml'}

# --- Blueprint Definition ---
bib_manager_bp = Blueprint(
    BIB_MANAGER_BLUEPRINT_NAME,
    __name__,
    template_folder='../templates/html/bib_manager', 
    url_prefix='/admin/bibliography'
)

# --- Helper Functions ---
def get_bibliographies_dir(app_instance):
    # Ensure BIB_DIR is correctly fetched from config, with a sensible default
    return app_instance.config.get('BIB_DIR', os.path.join(app_instance.root_path, 'data', 'bibliographies'))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Route Protection Helper ---
def admin_required_for_bib_manager(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        app_instance = getattr(g, 'app', current_app._get_current_object()) 

        if not ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY:
            app_instance.logger.error("BibManagerPlugin: admin_required check failed - acl_plugin components FAILED TO IMPORT.")
            flash("Admin functionality is disabled because the ACL system components are not available.", "error")
            abort(503) 

        current_user = getattr(g, 'current_user', None) 
        app_instance.logger.debug(f"BibManagerPlugin: admin_required checking user '{current_user}' for 'admin_site'.")

        if not main_acl_check_permission(app_instance, current_user, "admin_site", resource_path="SITE_ADMIN_BIB_MANAGER"):
            app_instance.logger.warning(f"BibManagerPlugin: Permission DENIED for user '{current_user}' to 'admin_site' (bibliography management).")
            flash("You do not have permission to access bibliography management.", "error")
            if current_user is None:
                return redirect(url_for('auth_plugin.login_route', next=request.url))
            else:
                abort(403) 
        
        app_instance.logger.debug(f"BibManagerPlugin: admin_required PASSED for user '{current_user}'")
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---
@bib_manager_bp.route('/', methods=['GET', 'POST'])
@admin_required_for_bib_manager
def manage_bibliographies():
    app_instance = g.app 
    bib_dir = get_bibliographies_dir(app_instance)
    
    if not os.path.exists(bib_dir):
        try:
            os.makedirs(bib_dir)
            app_instance.logger.info(f"BibManagerPlugin: Created bibliographies directory at {bib_dir}")
        except OSError as e:
            app_instance.logger.error(f"BibManagerPlugin: Could not create bibliographies directory {bib_dir}: {e}")
            flash(f"Error: Bibliographies directory could not be created at {bib_dir}.", "error")
            # Pass app_instance to the template context as 'app'
            return render_template('manage_bibliographies.html', title="Manage Bibliography Files", files=[], app=app_instance)


    if request.method == 'POST':
        if 'bibfile' not in request.files:
            flash('No file part in the request.', 'error')
            return redirect(request.url)
        
        file = request.files['bibfile']
        if file.filename == '':
            flash('No selected file.', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            upload_path = os.path.join(bib_dir, filename)
            
            if os.path.exists(upload_path):
                flash(f"File '{filename}' already exists. Please rename or delete the existing file first.", "warning")
            else:
                try:
                    file.save(upload_path)
                    flash(f"File '{filename}' uploaded successfully.", "success")
                    app_instance.logger.info(f"BibManagerPlugin: File '{filename}' uploaded to {bib_dir}")
                except Exception as e:
                    app_instance.logger.error(f"BibManagerPlugin: Error saving uploaded file '{filename}': {e}")
                    flash(f"Error uploading file '{filename}': {e}", "error")
            return redirect(url_for('.manage_bibliographies'))
        else:
            flash('Invalid file type. Allowed types are: ' + ', '.join(ALLOWED_EXTENSIONS), 'error')
            return redirect(request.url)

    bib_files = []
    if os.path.exists(bib_dir):
        try:
            for f_name in os.listdir(bib_dir):
                if allowed_file(f_name) and os.path.isfile(os.path.join(bib_dir, f_name)): 
                    bib_files.append(f_name)
        except Exception as e:
            app_instance.logger.error(f"BibManagerPlugin: Error listing files in {bib_dir}: {e}")
            flash("Error listing bibliography files.", "error")

    # Pass app_instance to the template context as 'app'
    return render_template('manage_bibliographies.html', title="Manage Bibliography Files", files=sorted(bib_files), app=app_instance)

@bib_manager_bp.route('/delete/<path:filename>', methods=['POST'])
@admin_required_for_bib_manager
def delete_bibliography_file(filename):
    app_instance = g.app
    bib_dir = get_bibliographies_dir(app_instance)
    
    safe_filename = secure_filename(filename) 
    if safe_filename != filename or '/' in filename or '\\' in filename:
        app_instance.logger.warning(f"BibManagerPlugin: Attempt to delete potentially unsafe filename '{filename}'. Sanitized to '{safe_filename}'. Denying if different or contains slashes.")
        flash("Invalid filename for deletion attempt.", "error")
        return redirect(url_for('.manage_bibliographies'))

    file_path = os.path.join(bib_dir, safe_filename)

    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            os.remove(file_path)
            flash(f"File '{safe_filename}' deleted successfully.", "success")
            app_instance.logger.info(f"BibManagerPlugin: Deleted file '{file_path}'")
        except Exception as e:
            flash(f"Error deleting file '{safe_filename}': {e}", "error")
            app_instance.logger.error(f"BibManagerPlugin: Error deleting file '{file_path}': {e}")
    else:
        flash(f"File '{safe_filename}' not found for deletion.", "error")
        app_instance.logger.warning(f"BibManagerPlugin: Attempted to delete non-existent file '{file_path}'")
        
    return redirect(url_for('.manage_bibliographies'))


# --- Plugin Registration ---
def register(app_instance, register_hook_func): 
    @app_instance.before_request 
    def bib_manager_before_request_setup(): 
        if request.blueprint == BIB_MANAGER_BLUEPRINT_NAME: 
            if not hasattr(g, 'app'): 
                g.app = app_instance 
            if not hasattr(g, 'current_user'): 
                g.current_user = session.get('current_user')
            app_instance.logger.debug(f"BibManagerPlugin: before_request - g.app set, g.current_user='{g.get('current_user')}' for blueprint {request.blueprint}")

    if not ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY:
        app_instance.logger.error("BibManagerPlugin: CRITICAL - Cannot register blueprint because acl_plugin components failed to import.")
        return

    app_instance.register_blueprint(bib_manager_bp) 
    app_instance.logger.info(f"Bibliography Manager plugin registered with routes at {bib_manager_bp.url_prefix}.")

    bib_dir_startup = get_bibliographies_dir(app_instance)
    if not os.path.exists(bib_dir_startup):
        try:
            os.makedirs(bib_dir_startup)
            app_instance.logger.info(f"BibManagerPlugin: Created bibliographies directory at {bib_dir_startup} during registration.")
        except OSError as e:
            app_instance.logger.error(f"BibManagerPlugin: Could not create bibliographies directory {bib_dir_startup} during registration: {e}")

