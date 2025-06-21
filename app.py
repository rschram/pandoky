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
                
                # Pass the kwargs dict through, so plugins can share data
                modified_result = function(*current_args, **kwargs)
                if modified_result is not None: 
                    data_to_modify = modified_result
            else:
                # This branch handles hooks that don't modify the first argument
                function(*args, **kwargs)

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


load_plugins()
trigger_hook('app_initialized', app=app) 

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
    if not s: return ""
    html = pypandoc.convert_text(s, 'html5', format='markdown')
    html = html.replace('<p>', '', 1).replace('</p>', '', 1).strip()
    return Markup(html)

def absolutize_internal_links(html_content, page_name=None):
    if not html_content or not page_name: return html_content
    try:
        base_url = url_for('view_page', page_name=page_name)
        absolute_html = re.sub(r'href="#', f'href="{base_url}#', html_content)
        return Markup(absolute_html)
    except Exception as e:
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
app.jinja_env.filters['anydate'] = anydate_filter
app.jinja_env.filters['markdown'] = markdown_filter
app.jinja_env.filters['absolutize'] = absolutize_internal_links

# --- Wikilink and Slugify Helper Functions ---
def slugify(text):
    text = str(text).lower()
    text = re.sub(r'\s+', '-', text) 
    text = re.sub(r'[^\w\-]', '', text) 
    return text

def convert_wikilinks(markdown_content):
    def replace_wikilink(match):
        full_link_text = match.group(1).strip()
        display_text, target_path_str = (full_link_text, full_link_text)
        if '|' in full_link_text:
            target_path_str, display_text = map(str.strip, full_link_text.split('|', 1))
        normalized_path_str = target_path_str.replace(':', '/')
        path_components = [slugify(comp.strip()) for comp in normalized_path_str.split('/') if comp.strip()]
        if not path_components: return f'[[{full_link_text}]]' 
        final_slug = '/'.join(path_components)
        if '|' not in full_link_text: display_text = directory_elements[-1] if (directory_elements := normalized_path_str.split('/')) else final_slug
        return f'[{display_text}]({url_for("view_page", page_name=final_slug)} "{target_path_str.replace(":", " > ")}")'
    return re.sub(r'\[\[([^\]]+)\]\]', replace_wikilink, markdown_content)

def render_markdown_from_template(template_name, **context):
    try:
        template = md_jinja_env.get_template(template_name)
        return template.render(context)
    except Exception as e:
        app.logger.error(f"Error rendering Markdown template {template_name}: {e}")
        raise

def _get_cache_path(page_name_slug):
    safe_slug = page_name_slug.replace('/', '__')
    cache_filename = f"{safe_slug}.html"
    html_cache_dir = os.path.join(app.config['CACHE_DIR'], 'html')
    os.makedirs(html_cache_dir, exist_ok=True)
    return os.path.join(html_cache_dir, cache_filename)

# --- Error Handlers ---
@app.errorhandler(403)
def forbidden_page(error): return render_template('html/errors/403.html', error=error), 403
@app.errorhandler(404)
def page_not_found_error(error): return render_template('html/errors/404.html', error=error), 404
@app.route('/favicon.ico')
def favicon(): return '', 204

# --- Routes ---
@app.route('/admin/acl')
@app.route('/admin/acl/')
def redirect_to_admin_dashboard():
    app.logger.debug("Redirecting /admin/acl to /admin/acl/dashboard")
    return redirect('/admin/acl/dashboard', code=301)

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
    page_extension = app.config['PAGE_EXTENSION']
    normalized_page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    if page_name != normalized_page_name:
        return redirect(url_for('view_page', page_name=normalized_page_name), code=308)
    page_name = normalized_page_name
    try:
        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + page_extension)
        page_name = trigger_hook('before_page_file_access', page_name, page_file_path=page_file_path, app_context=app)
        if not os.path.exists(page_file_path) or not os.path.isfile(page_file_path):
            return redirect(url_for('edit_page', page_name=page_name))
        with open(page_file_path, 'r', encoding='utf-8') as f:
            article = frontmatter.load(f)
        hook_data = {'frontmatter': article.metadata, 'body': article.content, 'page_name': page_name}
        modified_data = trigger_hook('after_page_load', hook_data, app_context=app)
        return modified_data or hook_data, page_name
    except PermissionError as e: 
        flash(str(e), "error")
        if session.get('current_user') is None: return redirect(url_for('auth_plugin.login_route', next=request.url))
        else: abort(403) 
    except Exception as e:
        app.logger.error(f"Unexpected error for page {page_name}: {e}", exc_info=True)
        flash(f"Error loading page '{page_name}'.", "error")
        return redirect(url_for('index'))


def _process_markdown_content(modified_data, page_name):
    """Process markdown content with hooks/macros."""
    try:
        original_frontmatter = modified_data.get('frontmatter', {})
        original_markdown_body = modified_data.get('body', '')
        md_render_context = {'frontmatter': original_frontmatter, 'body': original_markdown_body, 'page_name': page_name, 'config': app.config}
        markdown_template_name = original_frontmatter.get('markdown_template', 'article_template.j2md')
        processed_markdown_from_j2 = render_markdown_from_template(markdown_template_name, **md_render_context)
        processed_article_parts = frontmatter.loads(processed_markdown_from_j2)
        pandoc_input_frontmatter = processed_article_parts.metadata
        pandoc_input_body = processed_article_parts.content
        
        # --- MODIFICATION 1: Pass a dictionary to collect data from hooks ---
        hook_shared_data = {}
        
        pandoc_input_body = trigger_hook('process_page_macros', pandoc_input_body, current_page_slug=page_name, app_context=app, **hook_shared_data)
        pandoc_input_body = trigger_hook('process_media_links', pandoc_input_body, current_page_slug=page_name, app_context=app, **hook_shared_data)
        pandoc_input_body_with_wikilinks = convert_wikilinks(pandoc_input_body)

        final_markdown_for_pandoc = f"---\n{yaml.dump(pandoc_input_frontmatter, sort_keys=False, allow_unicode=True)}---\n\n{pandoc_input_body_with_wikilinks}"
        
        # --- MODIFICATION 2: Return both the markdown and the collected data ---
        return final_markdown_for_pandoc, hook_shared_data

    except Exception as e:
        app.logger.error(f"Error processing markdown for page {page_name}: {e}", exc_info=True)
        flash(f"The page '{page_name}' could not be processed due to a content error.", "error")
        return redirect(url_for('edit_page', page_name=page_name))

def _render_page_html(final_markdown_for_pandoc, page_name, page_title, original_frontmatter, discovered_metadata=None):
    """Convert processed markdown to HTML using Pandoc."""
    try:
        pandoc_args = list(app.config.get('PANDOC_ARGS', [])) # Use list() to ensure it's a mutable copy
        
        # --- MODIFICATION 3: Use the discovered metadata to augment pandoc_args ---
        if discovered_metadata and 'discovered_bibliographies' in discovered_metadata:
            bib_dir = app.config.get('BIB_DIR', 'data/bibliographies')
            for bib_file in discovered_metadata['discovered_bibliographies']:
                # Construct full, safe path and add to args
                full_bib_path = safe_join(bib_dir, bib_file)
                if full_bib_path and os.path.exists(full_bib_path):
                    pandoc_args.append(f'--bibliography={full_bib_path}')
                else:
                    app.logger.warning(f"Discovered bibliography '{bib_file}' not found at '{full_bib_path}'.")

        pandoc_args = trigger_hook('before_pandoc_conversion', pandoc_args, markdown_content=final_markdown_for_pandoc, app_context=app)
        
        html_content_fragment = pypandoc.convert_text(to='html5', format='markdown', source=final_markdown_for_pandoc, extra_args=pandoc_args)
        
        html_content_fragment = trigger_hook('after_pandoc_conversion', html_content_fragment, page_name=page_name, app_context=app)
        cache_path = _get_cache_path(page_name)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f: f.write(html_content_fragment)
            app.logger.info(f"HTML for page '{page_name}' saved to cache: {cache_path}")
        except Exception as e:
            app.logger.error(f"Failed to write to cache for page '{page_name}': {e}")

        render_context = {'title': page_title, 'html_content': html_content_fragment, 'frontmatter': original_frontmatter, 'page_name': page_name}
        render_context = trigger_hook('before_html_render', dict(render_context), app_context=app)
        return render_template('html/page_layout.html', **render_context)

    except RuntimeError as e: 
        flash(f"The page '{page_name}' could not be displayed due to a rendering error: {e}", "error")
        return redirect(url_for('edit_page', page_name=page_name))
    except Exception as e:
        app.logger.error(f"Unexpected error rendering HTML for page {page_name}: {e}", exc_info=True)
        flash(f"The page '{page_name}' could not be rendered due to an unexpected error.", "error")
        return redirect(url_for('edit_page', page_name=page_name))

def _get_lock_path(page_name_slug):
    safe_slug = page_name_slug.replace('/', '__')
    lock_filename = f"{safe_slug}.lock"
    return os.path.join(app.config['LOCKS_DIR'], lock_filename)

# ----

@app.route('/<path:page_name>')
def view_page(page_name):
    # Caching Logic remains the same...
    cache_path, source_path = _get_cache_path(page_name), safe_join(app.config['PAGES_DIR'], page_name + app.config['PAGE_EXTENSION'])
    if os.path.exists(cache_path) and os.path.exists(source_path) and os.path.getmtime(cache_path) > os.path.getmtime(source_path):
        app.logger.info(f"Serving '{page_name}' from cache.")
        try:
            with open(cache_path, 'r', encoding='utf-8') as f: cached_html = f.read()
            with open(source_path, 'r', encoding='utf-8') as f: article = frontmatter.load(f)
            page_title = article.metadata.get('title', page_name.replace('/', ' / ').title())
            return render_template('html/page_layout.html', title=page_title, html_content=cached_html, frontmatter=article.metadata, page_name=page_name)
        except Exception as e:
            app.logger.error(f"Error reading cache for '{page_name}': {e}")
    
    result = _get_page_data(page_name)
    if not isinstance(result, tuple): return result
    modified_data, final_page_name = result
    page_title = modified_data.get('frontmatter', {}).get('title', page_name.replace('/', ' / ').title()) 
    
    # --- MODIFICATION 4: Capture the extra data from processing ---
    final_markdown_for_pandoc, discovered_metadata = _process_markdown_content(modified_data, final_page_name)
    if isinstance(final_markdown_for_pandoc, tuple): # Handle error case where redirect is returned
        return final_markdown_for_pandoc
    
    # --- MODIFICATION 5: Pass the extra data to the renderer ---
    return _render_page_html(final_markdown_for_pandoc, final_page_name, page_title, original_frontmatter=modified_data.get('frontmatter', {}), discovered_metadata=discovered_metadata)


# ... (The rest of your app.py file remains the same) ...

@app.route('/<path:page_name>/edit', methods=['GET'])
def edit_page(page_name):
    normalized_page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    if page_name != normalized_page_name:
        return redirect(url_for('edit_page', page_name=normalized_page_name), code=308)
    page_name = normalized_page_name
    
    try:
        from plugins.acl_plugin import check_permission
        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + '.md')
        page_exists_check = os.path.exists(page_file_path) and os.path.isfile(page_file_path)
        required_action = "edit_page" if page_exists_check else "create_page"

        if not check_permission(app, g.get('current_user'), required_action, page_name):
             if g.get('current_user') is None:
                 flash(f"You must be logged in to {required_action.replace('_page', '')} pages.", "warning")
                 return redirect(url_for('auth_plugin.login_route', next=request.url))
             else:
                 flash(f"You do not have permission to {required_action.replace('_page', '')} this page.", "error")
                 abort(403)

        lock_path = _get_lock_path(page_name)
        locks_dir = app.config['LOCKS_DIR']
        os.makedirs(locks_dir, exist_ok=True)
        if os.path.exists(lock_path):
            try:
                with open(lock_path, 'r', encoding='utf-8') as f:
                    lock_timestamp_str, lock_user = f.read().strip().split(';', 1)
                lock_time = datetime.fromisoformat(lock_timestamp_str)
                time_since_lock = (datetime.now() - lock_time).total_seconds()
                if time_since_lock > app.config.get('LOCK_TIMEOUT', 1800):
                    os.remove(lock_path)
                elif lock_user != g.get('current_user', 'anonymous'):
                    flash(f"This page is locked by '{lock_user}'.", "warning")
                    return redirect(url_for('view_page', page_name=page_name))
            except Exception as e:
                os.remove(lock_path)
        with open(lock_path, 'w', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()};{g.get('current_user', 'anonymous')}")
        app.logger.info(f"Lock created for page '{page_name}' at {lock_path}")
    except PermissionError as e: 
        flash(str(e), "error")
        if g.get('current_user') is None: return redirect(url_for('auth_plugin.login_route', next=url_for('edit_page', page_name=page_name)))
        else: return redirect(url_for('view_page', page_name=page_name))

    default_title = page_name.replace('/', ' / ').title() 
    if page_exists_check: 
        with open(page_file_path, 'r', encoding='utf-8') as f: raw_content = f.read()
    else: 
        raw_content = f"---\ntitle: \"{default_title}\"\ndate: \"{datetime.now().strftime('%Y-%m-%d')}\"\nauthor: \"{g.get('current_user', 'Your Name')}\"\n---\n\nStart writing..."
    
    edit_page_data = {'page_name': page_name, 'raw_content': raw_content, 'title': f"Edit {default_title}", 'page_exists': page_exists_check}
    edit_page_data = trigger_hook('before_edit_page_render', dict(edit_page_data), app_context=app)
    return render_template('html/edit_page.html', **edit_page_data)

@app.route('/<path:page_name>/save', methods=['POST'])
def save_page(page_name):
    page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    try:
        raw_content_from_form = request.form.get('raw_content')
        if raw_content_from_form is None: abort(400, "No content.")
        raw_content_to_save = trigger_hook('before_page_save', raw_content_from_form, page_name=page_name, app_context=app)
        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + '.md')
        os.makedirs(os.path.dirname(page_file_path), exist_ok=True)
        with open(page_file_path, 'w', encoding='utf-8') as f: f.write(raw_content_to_save)
        flash(f"Page '{page_name}' saved.", "success")
        trigger_hook('after_page_save', page_name, file_path=page_file_path, app_context=app)
        lock_path = _get_lock_path(page_name)
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
                app.logger.info(f"Lock file removed for page: {page_name}")
            except OSError as e:
                app.logger.error(f"Error removing lock file {lock_path}: {e}")
        return redirect(url_for('view_page', page_name=page_name))
    except PermissionError as e: 
        flash(str(e), "error")
        if g.get('current_user') is None: return redirect(url_for('auth_plugin.login_route', next=url_for('edit_page', page_name=page_name)))
        else: return redirect(url_for('edit_page', page_name=page_name))
    except Exception as e:
        flash("Error saving page.", "error")
        return redirect(url_for('edit_page', page_name=page_name))

@app.route('/<path:page_name>/delete', methods=['POST'])
def delete_page(page_name):
    page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    try:
        page_file_path = safe_join(app.config['PAGES_DIR'], page_name + '.md')
        if trigger_hook('before_page_delete', False, page_name=page_name, file_path=page_file_path, app_context=app):
             return redirect(url_for('edit_page', page_name=page_name))
        if os.path.exists(page_file_path) and os.path.isfile(page_file_path):
            os.remove(page_file_path)
            flash(f"Page '{page_name}' deleted.", "success")
            trigger_hook('after_page_delete', page_name, file_path=page_file_path, app_context=app)
            for path_func in [_get_lock_path, _get_cache_path]:
                path = path_func(page_name)
                if os.path.exists(path): os.remove(path)
            return redirect(url_for('index')) 
        else:
            flash(f"Page '{page_name}' not found.", "error")
            return redirect(url_for('index'))
    except Exception as e: 
        flash(f"Error deleting page '{page_name}': {e}", "error")
        return redirect(url_for('index'))

@app.route('/<path:page_name>/cancel-edit', methods=['POST'])
def cancel_edit(page_name):
    page_name = '/'.join(slugify(part) for part in filter(None, page_name.split('/')))
    lock_path = _get_lock_path(page_name)
    if os.path.exists(lock_path):
        try:
            with open(lock_path, 'r', encoding='utf-8') as f:
                _lock_timestamp, lock_user = f.read().strip().split(';', 1)
            if lock_user == g.get('current_user'):
                os.remove(lock_path)
                flash("Edit canceled.", "info")
            else:
                flash("You cannot unlock this page.", "error")
        except Exception as e:
            flash("Error canceling edit.", "error")
    return redirect(url_for('view_page', page_name=page_name))

# --- Route to Serve Media Files ---
@app.route('/media/<path:filename>')
def serve_media_file(filename):
    media_dir = app.config.get('MEDIA_DIR')
    if not media_dir or ".." in filename or filename.startswith("/"): abort(404)
    return send_from_directory(media_dir, filename)

if __name__ == '__main__':
    try:
        pypandoc.get_pandoc_version()
    except OSError:
        app.logger.error("Pandoc not found.")
    app.run()
