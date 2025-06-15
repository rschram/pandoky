from flask import Flask, render_template, abort, request, redirect, url_for, flash, g, session, send_from_directory
from flask_mail import Mail, Message
from werkzeug.utils import safe_join 
import os
import re 
import yaml 
import frontmatter
from markupsafe import Markup
import pypandoc 
from jinja2 import Environment, FileSystemLoader, select_autoescape
from datetime import datetime 
import dateparser 
import importlib.util 
import sys 
from collections import defaultdict

# Initialize Flask App
app = Flask(__name__)
app.config.from_object('config') 
mail = Mail(app)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_for_dev_only_shh')

# --- Plugin System ---
PLUGIN_HOOKS = defaultdict(list)
PLUGINS_DIR = os.path.join(app.root_path, 'plugins')

def register_hook(hook_name, function):
    PLUGIN_HOOKS[hook_name].append(function)
    app.logger.info(f"Registered function {function.__name__} for hook '{hook_name}'")

def trigger_hook(hook_name, *args, **kwargs):
    data_to_modify = args[0] if args else None
    
    for function in PLUGIN_HOOKS[hook_name]:
        try:
            if data_to_modify is not None and args: 
                current_args = list(args)
                current_args[0] = data_to_modify
                
                modified_result = function(*current_args, **kwargs)
                if modified_result is not None: 
                    data_to_modify = modified_result
            else:
                result = function(*args, **kwargs)
                if data_to_modify is None and args and result is not None:
                    data_to_modify = result

            app.logger.debug(f"Executed hook '{hook_name}' with function {function.__name__}")
        except PermissionError: 
            raise
        except Exception as e:
            app.logger.error(f"Error executing hook '{hook_name}' with function {function.__name__}: {e}", exc_info=True)
    
    return data_to_modify

app.trigger_hook = trigger_hook

def load_plugins():
    if not os.path.exists(PLUGINS_DIR):
        app.logger.info(f"Plugins directory '{PLUGINS_DIR}' not found. Skipping plugin loading.")
        return
    
    if PLUGINS_DIR not in sys.path:
        sys.path.insert(0, PLUGINS_DIR)

    for item_name in os.listdir(PLUGINS_DIR):
        item_path = os.path.join(PLUGINS_DIR, item_name)
        
        if item_name.endswith('.py') and not item_name.startswith('_'):
            module_name = item_name[:-3]
            try:
                spec = importlib.util.spec_from_file_location(module_name, item_path)
                plugin_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(plugin_module)
                if hasattr(plugin_module, 'register'):
                    plugin_module.register(app, register_hook) 
                    app.logger.info(f"Loaded plugin: {module_name}")
                else:
                    app.logger.warning(f"Plugin {module_name} has no register() function.")
            except Exception as e:
                app.logger.error(f"Failed to load plugin {module_name}: {e}", exc_info=True)
        
        elif os.path.isdir(item_path) and not item_name.startswith('_') and os.path.exists(os.path.join(item_path, '__init__.py')):
            module_name = item_name
            try:
                plugin_module = importlib.import_module(module_name)
                if hasattr(plugin_module, 'register'):
                    plugin_module.register(app, register_hook) 
                    app.logger.info(f"Loaded plugin package: {module_name}")
                else:
                    app.logger.warning(f"Plugin package {module_name} has no register() function in its __init__.py.")
            except Exception as e:
                app.logger.error(f"Failed to load plugin package {module_name}: {e}", exc_info=True)

# --- Custom Jinja2 Filter Definition ---
def anydate_filter(value, format_string="%B %d, %Y"):
    if not value: return ""
    try:
        parsed_date = dateparser.parse(str(value))
        return parsed_date.strftime(format_string) if parsed_date else str(value)
    except Exception as e:
        app.logger.error(f"Error in anydate_filter for value '{value}': {e}")
        return str(value)

def markdown_filter(s):
    """
    Converts a Markdown string to HTML and marks it as safe.
    This filter is for inline, simple markdown.
    """
    if not s:
        return ""
    # Convert markdown to an HTML fragment
    html = pypandoc.convert_text(s, 'html5', format='markdown')
    # Remove the <p>...</p> tags that pandoc adds to simple strings
    html = html.replace('<p>', '', 1).replace('</p>', '', 1).strip()
    return Markup(html)

def absolutize_internal_links(html_content, page_name=None):
    """
    Finds all internal anchor links (e.g., href="#footnote1") in a block
    of HTML and prepends the full URL for the current page to them.
    """
    if not html_content or not page_name:
        return html_content

    try:
        # Generate the base URL for the current page
        base_url = url_for('view_page', page_name=page_name)

        # This regex looks for 'href="' followed by a '#' and replaces it
        # with 'href="/path/to/page#'. It's a simple and safe substitution.
        # It won't affect absolute URLs (like http://...) or other relative links.
        absolute_html = re.sub(r'href="#', f'href="{base_url}#', html_content)

        # Mark the processed HTML as safe to prevent auto-escaping
        return Markup(absolute_html)
    except Exception as e:
        # In case url_for fails for any reason, log it and return original content
        app.logger.error(f"Error in absolutize_internal_links filter: {e}")
        return html_content

# --- Jinja2 Environment for Markdown Templates ---
md_template_dir = os.path.join(app.root_path, 'templates', 'markdown')
md_jinja_env = Environment(
    loader=FileSystemLoader(md_template_dir),
    autoescape=select_autoescape(['md']),
    trim_blocks=True,
    lstrip_blocks=True
)
md_jinja_env.filters['anydate'] = anydate_filter
md_jinja_env.filters['markdown'] = markdown_filter
md_jinja_env.filters['absolutize'] = absolutize_internal_links
# --- Register Custom Filter with Flask's Main Jinja2 Environment ---
app.jinja_env.filters['anydate'] = anydate_filter
app.jinja_env.filters['markdown'] = markdown_filter
app.jinja_env.filters['absolutize'] = absolutize_internal_links

# --- Wikilink and Slugify Helper Functions ---
def slugify(text):
    """Converts text to a URL-friendly slug, typically for the last part of a path."""
    text = str(text).lower() # Ensure it's a string
    text = re.sub(r'\s+', '-', text) 
    text = re.sub(r'[^\w\-]', '', text) 
    return text

def convert_wikilinks(markdown_content):
    '''
    Converts [[Namespace:Sub/Page Name|Display Text]] to a Pandoky link.
    Handles namespaces separated by ':' or '/'.
    Slugifies all parts of the path.
    '''
    def replace_wikilink(match):
        full_link_text = match.group(1).strip()
        display_text = full_link_text
        target_path_str = full_link_text

        if '|' in full_link_text:
            target_path_str, display_text = map(str.strip, full_link_text.split('|', 1))

        normalized_path_str = target_path_str.replace(':', '/')
        link_title = target_path_str.replace(':', ' > ')
        directory_elements = normalized_path_str.split('/')
        page_link_text = directory_elements[-1]
        path_components = [slugify(comp.strip()) for comp in directory_elements if comp.strip()]

        if not path_components:
            return f'[[{full_link_text}]]' 

        final_slug = '/'.join(path_components)
            
        if '|' not in full_link_text:
            display_text = page_link_text #' / '.join(path_components)


        return f'[{display_text}]({url_for("view_page", page_name=final_slug)} "{link_title}")'

    wikilink_pattern = r'\[\[([^\]]+)\]\]'
    return re.sub(wikilink_pattern, replace_wikilink, markdown_content)


def render_markdown_from_template(template_name, **context):
    try:
        template = md_jinja_env.get_template(template_name)
        return template.render(context)
    except Exception as e:
        app.logger.error(f"Error rendering Markdown template {template_name}: {e}")
        raise

# --- Error Handlers ---
@app.errorhandler(403)
def forbidden_page(error):
    return render_template('html/errors/403.html', error=error), 403
@app.errorhandler(404)
def page_not_found_error(error): 
    return render_template('html/errors/404.html', error=error), 404
@app.route('/favicon.ico')
def favicon():
    return '', 204

# --- Routes ---
@app.route('/admin/acl')
@app.route('/admin/acl/')
def redirect_to_admin_dashboard(): # Renamed from redirect_to_admin_acl_base for clarity
    # Using a direct path redirect to avoid potential BuildError with url_for
    # This assumes the admin_acl_editor_plugin registers its dashboard at '/admin/acl/dashboard'.
    app.logger.debug("Redirecting /admin/acl to /admin/acl/dashboard")
    return redirect('/admin/acl/dashboard', code=301) # Use direct path


@app.route('/')
def index():
    try:
        trigger_hook('before_index_load', 'home', app_context=app) 
        return view_page('home')
    except Exception as e:
        app.logger.info(f"Home page not found or error: {e}")
        return "Welcome to Pandoky! Create 'data/pages/home.md' to get started.", 200

# -- View page helper functions --
def _get_page_data(page_name):
    """Retrieve data for the given page."""
    page_extension = app.config['PAGE_EXTENSION']
    normalized_page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    if page_name != normalized_page_name:
        app.logger.debug(f"Redirecting potentially unslugified URL '{page_name}' to '{normalized_page_name}'")
        return redirect(url_for('view_page', page_name=normalized_page_name), code=308)
    page_name = normalized_page_name

    try:
        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + page_extension)
        page_name = trigger_hook('before_page_file_access', page_name, page_file_path=page_file_path, app_context=app)

        if page_file_path is None:
            app.logger.error(f"Resolved page_file_path does not exist for page: {page_name}. Check the configuration settings.")
            return redirect(url_for('edit_page', page_name=page_name), code=308)

        if not os.path.exists(page_file_path) or not os.path.isfile(page_file_path):
            app.logger.warning(f"Page file not found: {page_file_path}. Redirecting to edit page.")
            return redirect(url_for('edit_page', page_name=page_name))

        with open(page_file_path, 'r', encoding='utf-8') as f:
            article = frontmatter.load(f)
        
        original_frontmatter = article.metadata
        original_markdown_body = article.content
        hook_data = {'frontmatter': original_frontmatter, 'body': original_markdown_body, 'page_name': page_name}
        modified_data = trigger_hook('after_page_load', hook_data, app_context=app)
        if modified_data:
            return modified_data, page_name
        else:
            return hook_data, page_name
    except PermissionError as e: 
        flash(str(e), "error")
        app.logger.warning(f"ACL Permission denied for viewing page {page_name}: {e}")
        user_in_session = session.get('current_user', None) 
        if user_in_session is None:
            return redirect(url_for('auth_plugin.login_route', next=request.url))
        else:
            abort(403) 
    except FileNotFoundError: 
        app.logger.error(f"File not found for page: {page_name}")
        abort(404) 
    except RuntimeError as e: 
        app.logger.error(f"Conversion error for page {page_name}: {e}")
        flash(f"The page '{page_name}' could not be displayed due to a rendering error. Please fix the issue below. (Details: {e})", "error")
        return redirect(url_for('edit_page', page_name=page_name))
    except Exception as e:
        app.logger.error(f"Unexpected error for page {page_name}: {e}", exc_info=True)
        flash(f"The page '{page_name}' could not be displayed due to an unexpected error. Please fix the issue below. (Details: {e})", "error")
        return redirect(url_for('edit_page', page_name=page_name))


def _process_markdown_content(modified_data,page_name):
    """Process markdown content with hooks/macros."""
    try: 
        if modified_data: 
            original_frontmatter = modified_data.get('frontmatter', {}) if modified_data else {}
            original_markdown_body = modified_data.get('body', '') if modified_data else ''

        md_render_context = {
            'frontmatter': original_frontmatter,
            'body': original_markdown_body, 
            'page_name': page_name,
            'config': app.config
        }
        
        markdown_template_name = original_frontmatter.get('markdown_template', 'article_template.j2md')
        processed_markdown_from_j2 = render_markdown_from_template(markdown_template_name, **md_render_context)

        processed_article_parts = frontmatter.loads(processed_markdown_from_j2)
        pandoc_input_frontmatter = processed_article_parts.metadata
        pandoc_input_body = processed_article_parts.content
        
        pandoc_input_body = trigger_hook('process_page_macros', pandoc_input_body, current_page_slug=page_name, app_context=app)

        pandoc_input_body = trigger_hook('process_media_links', pandoc_input_body, current_page_slug=page_name, app_context=app)
        
        pandoc_input_body = trigger_hook('before_wikilink_conversion', pandoc_input_body, frontmatter=pandoc_input_frontmatter, app_context=app)
        pandoc_input_body_with_wikilinks = convert_wikilinks(pandoc_input_body)
        pandoc_input_body_with_wikilinks = trigger_hook('after_wikilink_conversion', pandoc_input_body_with_wikilinks, frontmatter=pandoc_input_frontmatter, app_context=app)

        final_markdown_for_pandoc = f"---\n{yaml.dump(pandoc_input_frontmatter, sort_keys=False, allow_unicode=True)}---\n\n{pandoc_input_body_with_wikilinks}"
        return final_markdown_for_pandoc
    except RuntimeError as e: 
        app.logger.error(f"Conversion error for page {page_name}: {e}")
        flash(f"The page '{page_name}' could not be displayed due to a rendering error. Please fix the issue below. (Details: {e})", "error")
        return redirect(url_for('edit_page', page_name=page_name))
    except Exception as e:
        app.logger.error(f"Unexpected error for page {page_name}: {e}", exc_info=True)
        flash(f"The page '{page_name}' could not be displayed due to an unexpected error. Please fix the issue below. (Details: {e})", "error")
        return redirect(url_for('edit_page', page_name=page_name))

def _render_page_html(final_markdown_for_pandoc, page_name, page_title, original_frontmatter):
    """Convert processed markdown to HTML using Pandoc."""
    try:
        
        pandoc_args = app.config['PANDOC_ARGS']
        
        pandoc_args = trigger_hook('before_pandoc_conversion', list(pandoc_args), markdown_content=final_markdown_for_pandoc, app_context=app)
        
        html_content_fragment = pypandoc.convert_text(
            to='html5',
            format='markdown',
            source=final_markdown_for_pandoc,
            extra_args=pandoc_args,
        )
        
        html_content_fragment = trigger_hook('after_pandoc_conversion', html_content_fragment, page_name=page_name, app_context=app)
        
        render_context = {
            'title': page_title,
            'html_content': html_content_fragment,
            'frontmatter': original_frontmatter,
            'page_name': page_name
        }
        
        render_context = trigger_hook('before_html_render', dict(render_context), app_context=app)
        
        return render_template('html/page_layout.html', **render_context)

    except RuntimeError as e: 
        app.logger.error(f"Conversion error for page {page_name}: {e}")
        flash(f"The page '{page_name}' could not be displayed due to a rendering error. Please fix the issue below. (Details: {e})", "error")
        return redirect(url_for('edit_page', page_name=page_name))
    except Exception as e:
        app.logger.error(f"Unexpected error for page {page_name}: {e}", exc_info=True)
        flash(f"The page '{page_name}' could not be displayed due to an unexpected error. Please fix the issue below. (Details: {e})", "error")
        return redirect(url_for('edit_page', page_name=page_name))
# ----

@app.route('/<path:page_name>')
def view_page(page_name):
    result = _get_page_data(page_name)

    if not isinstance(result, tuple):
        return result  # It's a redirect or abort
    modified_data, final_page_name = result

    page_title = modified_data.get('frontmatter', {}).get('title', page_name.replace('/', ' / ').title()) 
    final_markdown_for_pandoc = _process_markdown_content(modified_data, final_page_name)

    return _render_page_html(final_markdown_for_pandoc, final_page_name, page_title, original_frontmatter=modified_data.get('frontmatter', {}))



@app.route('/<path:page_name>/edit', methods=['GET'])
def edit_page(page_name):
    normalized_page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    if page_name != normalized_page_name:
        app.logger.debug(f"Redirecting malformed URL in edit_page '{page_name}' to '{normalized_page_name}'")
        return redirect(url_for('edit_page', page_name=normalized_page_name), code=308)
    page_name = normalized_page_name


    try:
        from plugins.acl_plugin import check_permission as acl_check_permission 
        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + '.md')
        page_exists_check = os.path.exists(page_file_path) and os.path.isfile(page_file_path)
        
        required_action = "edit_page" if page_exists_check else "create_page"

        if not acl_check_permission(app, g.get('current_user'), required_action, page_name):
             if g.get('current_user') is None:
                 flash(f"You need to log in to {required_action.replace('_page', '')} pages.", "warning")
                 return redirect(url_for('auth_plugin.login_route', next=request.url))
             else:
                 flash(f"You do not have permission to {required_action.replace('_page', '')} this page.", "error")
                 abort(403)

        if os.path.exists(f"{page_file_path}.lock"):
            with open(f"{page_file_path}.lock", 'r', encoding='utf-8') as lock_file:
                lock_content = lock_file.read()
            flash(f"This page is currently locked for editing by another user. {lock_content}", "warning")
            app.logger.warning(f"Page {page_name} is locked for editing: {lock_content}.")
            return redirect(url_for('view_page', page_name=page_name))
        else:
            with open(f"{page_file_path}.lock", 'w', encoding='utf-8') as lock_file:
                lock_file.write(f"Editing {page_name} by {g.get('current_user', 'unknown user')} at {datetime.now().isoformat()}\n")
            app.logger.info(f"Lock file created for editing page: {page_file_path}.lock")

        default_title = page_name.replace('/', ' / ').title() 
        default_date = datetime.now().strftime('%Y-%m-%d') 
        
        if page_exists_check: 
            with open(page_file_path, 'r', encoding='utf-8') as f:
                raw_content = f.read()
        else: 
            raw_content = (
                f"---\n"
                f"doctype: \"Article\"\n"
                f"title: \"{default_title}\"\n"
                f"#subtitle: \"[...]\"\n"
                f"date: \"{default_date}\"\n"
                f"author: \"{g.get('current_user', 'Your Name')}\"\n"
                f"references-section-title: \"References\"\n"
                f"---\n\n"
                f"Start writing content for {default_title} here..."
            )
        
        edit_page_data = {'page_name': page_name, 'raw_content': raw_content, 'title': f"Edit {default_title}", 'page_exists': page_exists_check}
        edit_page_data = trigger_hook('before_edit_page_render', dict(edit_page_data), app_context=app)
            
        return render_template('html/edit_page.html', **edit_page_data)
    except PermissionError as e: 
        flash(str(e), "error")
        app.logger.warning(f"ACL Permission denied for editing page {page_name}: {e}")
        if g.get('current_user') is None: return redirect(url_for('auth_plugin.login_route', next=request.url))
        else: abort(403)
    except Exception as e:
        app.logger.error(f"Error loading edit page for {page_name}: {e}", exc_info=True)
        abort(500, description="Could not load the page for editing.")

@app.route('/<path:page_name>/save', methods=['POST'])
def save_page(page_name):
    normalized_page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    if page_name != normalized_page_name:
        app.logger.warning(f"Page name '{page_name}' in POST was normalized to '{normalized_page_name}'.")
        page_name = normalized_page_name

    try:
        raw_content_from_form = request.form.get('raw_content')
        if raw_content_from_form is None: 
            abort(400, description="No content submitted.")

        raw_content_to_save = trigger_hook('before_page_save', raw_content_from_form, page_name=page_name, app_context=app)

        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + '.md')
        
        page_directory = os.path.dirname(page_file_path)
        if not os.path.exists(page_directory):
            os.makedirs(page_directory, exist_ok=True)
            app.logger.info(f"Created directory: {page_directory}")
            
        with open(page_file_path, 'w', encoding='utf-8') as f:
            f.write(raw_content_to_save)
        
        flash(f"Page '{page_name}' saved successfully.", "success")
        app.logger.info(f"Page saved: {page_file_path}")
        
        trigger_hook('after_page_save', page_name, file_path=page_file_path, app_context=app)
        os.remove(f"{page_file_path}.lock")  # Remove the lock file after saving
        app.logger.info(f"Lock file removed for page: {page_file_path}.lock")

        return redirect(url_for('view_page', page_name=page_name))
    except PermissionError as e: 
        flash(str(e), "error")
        app.logger.warning(f"ACL Permission denied for saving page {page_name}: {e}")
        if g.get('current_user') is None:
            return redirect(url_for('auth_plugin.login_route', next=url_for('edit_page', page_name=page_name)))
        else:
            return redirect(url_for('edit_page', page_name=page_name))
    except Exception as e:
        flash(f"Error saving page '{page_name}': An unexpected error occurred.", "error")
        app.logger.error(f"Error saving page {page_name}: {e}", exc_info=True)
        return redirect(url_for('edit_page', page_name=page_name))


@app.route('/<path:page_name>/delete', methods=['POST'])
def delete_page(page_name):
    normalized_page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    page_name = normalized_page_name 

    try:
        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + '.md')

        cancel_delete_result = trigger_hook('before_page_delete', False, page_name=page_name, file_path=page_file_path, app_context=app)
        
        if cancel_delete_result is True: 
             return redirect(url_for('edit_page', page_name=page_name))

        if os.path.exists(page_file_path) and os.path.isfile(page_file_path):
            os.remove(page_file_path)
            flash(f"Page '{page_name}' deleted successfully.", "success")
            app.logger.info(f"Page deleted: {page_file_path}")
            trigger_hook('after_page_delete', page_name, file_path=page_file_path, app_context=app)
            return redirect(url_for('index')) 
        else:
            flash(f"Page '{page_name}' not found, cannot delete.", "error")
            app.logger.warning(f"Attempted to delete non-existent page: {page_file_path}")
            return redirect(url_for('index')) 

    except Exception as e: 
        flash(f"Error deleting page '{page_name}': {e}", "error")
        app.logger.error(f"Error deleting page {page_name}: {e}", exc_info=True)
        return redirect(url_for('index'))



# --- Route to Serve Media Files ---
@app.route('/media/<path:filename>') # Or use app.config['MEDIA_URL_PREFIX']
def serve_media_file(filename):
    media_dir = app.config.get('MEDIA_DIR')
    if not media_dir:
        app.logger.error("MEDIA_DIR not configured in app.config for serving media files.")
        abort(404)
    # For security, it's better if MEDIA_DIR is an absolute path.
    # safe_join can help, but send_from_directory expects the directory path directly.
    # Ensure filename is also sanitized or that the media_dir structure is flat for simplicity.
    # If allowing subdirectories in media_dir, ensure 'filename' is properly handled.
    
    # Basic check to prevent path traversal if filename could contain '..'
    # secure_filename might be too restrictive if you want subdirectories in media.
    # For now, assume filename is clean or refers to files directly in MEDIA_DIR.
    # A more robust solution would involve checking if the resolved path is within MEDIA_DIR.
    if ".." in filename or filename.startswith("/"):
         app.logger.warning(f"Potential path traversal attempt for media file: {filename}")
         abort(404)

    return send_from_directory(media_dir, filename)


# --- Load plugins (production) ---
#load_plugins()
#trigger_hook('app_initialized', app=app) 


if __name__ == '__main__':
    load_plugins()
    trigger_hook('app_initialized', app=app) 

    try:
        pypandoc.get_pandoc_version()
        app.logger.info(f"Pandoc version: {pypandoc.get_pandoc_version()} found.")
    except OSError:
        app.logger.error("Pandoc not found. Please ensure Pandoc is installed and in your system's PATH.")
    except Exception as e: 
        app.logger.error(f"Error initializing or finding pypandoc: {e}")

    app.run()
