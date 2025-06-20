# pandoky/plugins/media_manager_plugin.py

import os
import re
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, g, current_app, session, abort, send_from_directory
)
from werkzeug.utils import secure_filename
from functools import wraps
import sys

# --- Attempt to import from the main acl_plugin ---
ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY = False
try:
    from plugins.acl_plugin import ( 
        check_permission as main_acl_check_permission
    )
    ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY = True
except ImportError as e:
    print(f"MediaManagerPlugin: WARNING - Could not import from acl_plugin: {e}. Admin check fallback will be used.")
    def main_acl_check_permission(app_instance, username, required_action, resource_path=None):
        if hasattr(app_instance, 'logger'):
            app_instance.logger.error("MediaManagerPlugin: Using fallback main_acl_check_permission - acl_plugin FAILED TO IMPORT or is misconfigured.")
        return False

# --- Configuration ---
MEDIA_MANAGER_BLUEPRINT_NAME = 'media_manager_plugin'
# MEDIA_DIR and ALLOWED_MEDIA_EXTENSIONS will be taken from app.config

# --- Blueprint Definition ---
media_manager_bp = Blueprint(
    MEDIA_MANAGER_BLUEPRINT_NAME,
    __name__,
    template_folder='../templates/html/media_manager', 
    url_prefix='/admin/media'
)

# --- Helper Functions ---
def get_media_dir(app_instance):
    # Get from app.config, which should be set up from config.py
    return app_instance.config.get('MEDIA_DIR', os.path.join(app_instance.root_path, 'data', 'media'))

def allowed_media_file(app_instance, filename):
    allowed_extensions = app_instance.config.get('ALLOWED_MEDIA_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif'})
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

# --- Route Protection Helper ---
def admin_required_for_media_manager(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        app_instance = getattr(g, 'app', current_app._get_current_object()) 

        if not ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY:
            app_instance.logger.error("MediaManagerPlugin: admin_required check failed - acl_plugin components FAILED TO IMPORT.")
            flash("Admin functionality is disabled because the ACL system components are not available.", "error")
            abort(503) 

        current_user = getattr(g, 'current_user', None) 
        
        # Use the imported check_permission from acl_plugin
        if not main_acl_check_permission(app_instance, current_user, "admin_site", resource_path="SITE_ADMIN_MEDIA_MANAGER"):
            app_instance.logger.warning(f"MediaManagerPlugin: Permission DENIED for user '{current_user}' to 'admin_site' (media management).")
            flash("You do not have permission to access media management.", "error")
            if current_user is None:
                return redirect(url_for('auth_plugin.login_route', next=request.url))
            else:
                abort(403) 
        return f(*args, **kwargs)
    return decorated_function

# --- Routes for Admin Media Management ---
@media_manager_bp.route('/', methods=['GET', 'POST'])
@admin_required_for_media_manager
def manage_media_files():
    app_instance = g.app 
    media_dir = get_media_dir(app_instance)
    
    if not os.path.isdir(media_dir):
        try:
            os.makedirs(media_dir)
            app_instance.logger.info(f"MediaManagerPlugin: Created media directory at {media_dir}")
        except OSError as e:
            app_instance.logger.error(f"MediaManagerPlugin: Could not create media directory {media_dir}: {e}")
            flash(f"Error: Media directory could not be created at {media_dir}.", "error")
            return render_template('manage_media.html', title="Manage Media Files", files=[], app=app_instance)

    if request.method == 'POST':
        if 'mediafile' not in request.files:
            flash('No file part in the request.', 'error')
            return redirect(request.url)
        
        file = request.files['mediafile']
        if file.filename == '':
            flash('No selected file.', 'error')
            return redirect(request.url)
        
        if file and allowed_media_file(app_instance, file.filename):
            filename = secure_filename(file.filename)
            upload_path = os.path.join(media_dir, filename)
            
            if os.path.exists(upload_path):
                flash(f"File '{filename}' already exists. Please rename or delete the existing file first.", "warning")
            else:
                try:
                    file.save(upload_path)
                    flash(f"File '{filename}' uploaded successfully.", "success")
                    app_instance.logger.info(f"MediaManagerPlugin: File '{filename}' uploaded to {media_dir}")
                except Exception as e:
                    app_instance.logger.error(f"MediaManagerPlugin: Error saving uploaded file '{filename}': {e}")
                    flash(f"Error uploading file '{filename}': {e}", "error")
            return redirect(url_for('.manage_media_files'))
        else:
            allowed_ext_str = ', '.join(app_instance.config.get('ALLOWED_MEDIA_EXTENSIONS', set()))
            flash(f'Invalid file type. Allowed types are: {allowed_ext_str}', 'error')
            return redirect(request.url)

    media_files = []
    if os.path.exists(media_dir):
        try:
            for f_name in os.listdir(media_dir):
                if os.path.isfile(os.path.join(media_dir, f_name)) and allowed_media_file(app_instance, f_name): 
                    media_files.append({
                        "name": f_name,
                        "url": url_for('serve_media_file', filename=f_name) # Assumes serve_media_file route in main app
                    })
        except Exception as e:
            app_instance.logger.error(f"MediaManagerPlugin: Error listing files in {media_dir}: {e}")
            flash("Error listing media files.", "error")
    
    return render_template('manage_media.html', title="Manage Media Files", files=sorted(media_files, key=lambda x: x['name']), app=app_instance)

@media_manager_bp.route('/delete/<path:filename>', methods=['POST'])
@admin_required_for_media_manager
def delete_media_file_admin(filename): # Renamed to avoid conflict with potential main app route
    app_instance = g.app
    media_dir = get_media_dir(app_instance)
    
    safe_filename = secure_filename(filename) 
    if safe_filename != filename or '/' in safe_filename or '\\' in safe_filename:
        app_instance.logger.warning(f"MediaManagerPlugin: Attempt to delete potentially unsafe or nested filename '{filename}'. Denying.")
        flash("Invalid filename for deletion attempt.", "error")
        return redirect(url_for('.manage_media_files'))

    file_path = os.path.join(media_dir, safe_filename)

    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            os.remove(file_path)
            flash(f"File '{safe_filename}' deleted successfully.", "success")
            app_instance.logger.info(f"MediaManagerPlugin: Deleted file '{file_path}'")
        except Exception as e:
            flash(f"Error deleting file '{safe_filename}': {e}", "error")
            app_instance.logger.error(f"MediaManagerPlugin: Error deleting file '{file_path}': {e}")
    else:
        flash(f"File '{safe_filename}' not found for deletion or is not a file.", "error")
        app_instance.logger.warning(f"MediaManagerPlugin: Attempted to delete non-existent or non-file item '{file_path}'")
        
    return redirect(url_for('.manage_media_files'))

# --- Hook for Processing Media Links in Markdown ---
def process_media_links_hook(markdown_content, current_page_slug, app_context):
    """
    Finds relative image links like ![alt](image.png) and prepends the media URL prefix.
    Assumes images are directly in the MEDIA_DIR, not in subfolders relative to the page.
    """
    app_context.logger.debug(f"MediaManagerPlugin (HOOK: process_media_links) for page '{current_page_slug}'")
    
    media_url_prefix = app_context.config.get('MEDIA_URL_PREFIX', '/media')
    # Ensure prefix starts and ends with a slash for easy joining if needed, but url_for is better.
    # For simplicity, we'll just prepend the prefix if the link doesn't look like a full URL.

    # Regex to find Markdown images: ![alt text](image_path "optional title")
    # It captures:
    #   group 1: alt text
    #   group 2: image path
    #   group 3: optional title (including quotes)
    # This regex is simplified and might not cover all Markdown image syntax edge cases.
    # It specifically looks for paths that do NOT start with http://, https://, or / (already absolute)
    # and do not contain '://' (another check for full URLs).
    # It also tries to avoid matching data URIs.
    
    # More robust: find all ![...](...)
    # Then check if the path is relative.
    def replace_link(match):
        alt_text = match.group(1)
        image_path = match.group(2).strip()
        title_part = match.group(3) if match.group(3) else ""

        # Check if it's likely a relative path to a media file
        if not (image_path.startswith(('http://', 'https://', '/')) or '://' in image_path or image_path.startswith('data:')):
            # Assume it's a filename in the MEDIA_DIR
            # Generate URL using the main app's 'serve_media_file' route
            try:
                # Ensure the image_path is just the filename, not including subdirs for this simple version
                # If you allow subdirs in MEDIA_DIR, image_path could be 'subdir/image.png'
                # and serve_media_file route should handle it.
                
                # For now, assume image_path is just the filename.ext
                # If image_path could be "sub/image.png", then url_for('serve_media_file', filename=image_path)
                # would generate /media/sub/image.png, and serve_media_file needs to handle that.
                
                # Let's assume for now that image_path is just the filename.
                # If authors use "subdir/image.png", this will naturally become /media/subdir/image.png
                
                final_image_url = url_for('serve_media_file', filename=image_path)
                app_context.logger.debug(f"MediaManagerPlugin: Rewriting '{image_path}' to '{final_image_url}'")
                return f"![{alt_text}]({final_image_url}{title_part})"
            except Exception as e:
                app_context.logger.error(f"MediaManagerPlugin: Error building URL for media file '{image_path}': {e}. Link unchanged.")
                return match.group(0) # Return original match on error
        return match.group(0) # Return original if it looks like a full URL or absolute path

    # Regex for ![alt](path "title") or ![alt](path)
    # Group 1: Alt text. Group 2: Path. Group 3: Optional title part (e.g. " \"My Title\"")
    markdown_image_pattern = r'!\[(.*?)\]\((.*?)(?:\s+(".*?"|\'.*?\'))?\)'
    
    new_content = re.sub(markdown_image_pattern, replace_link, markdown_content)
    return new_content


# --- Plugin Registration ---
def register(app_instance, register_hook_func): 
    @app_instance.before_request 
    def media_manager_before_request_setup(): 
        if request.blueprint == MEDIA_MANAGER_BLUEPRINT_NAME: 
            if not hasattr(g, 'app'): 
                g.app = app_instance 
            if not hasattr(g, 'current_user'): 
                g.current_user = session.get('current_user')
            app_instance.logger.debug(f"MediaManagerPlugin: before_request - g.app set, g.current_user='{g.get('current_user')}' for blueprint {request.blueprint}")

    if not ACL_LOGIC_PLUGIN_IMPORTED_SUCCESSFULLY:
        app_instance.logger.error("MediaManagerPlugin: CRITICAL - Cannot register blueprint because acl_plugin components failed to import.")
        return

    app_instance.register_blueprint(media_manager_bp) 
    app_instance.logger.info(f"Media Manager plugin registered with routes at {media_manager_bp.url_prefix}.")

    # Register the hook for processing media links
    def _process_media_links_hook_wrapper(markdown_content, current_page_slug, **kwargs):
        actual_app_context = kwargs.get('app_context', app_instance)
        return process_media_links_hook(markdown_content, current_page_slug, app_context=actual_app_context)
    
    register_hook_func('process_media_links', _process_media_links_hook_wrapper) # New hook name
    app_instance.logger.info("MediaManagerPlugin: Registered for 'process_media_links' hook.")

    # Ensure the media directory exists on startup
    media_dir_startup = get_media_dir(app_instance)
    if not os.path.isdir(media_dir_startup): # Check if it's a directory
        try:
            os.makedirs(media_dir_startup)
            app_instance.logger.info(f"MediaManagerPlugin: Created media directory at {media_dir_startup} during registration.")
        except OSError as e:
            app_instance.logger.error(f"MediaManagerPlugin: Could not create media directory {media_dir_startup} during registration: {e}")

