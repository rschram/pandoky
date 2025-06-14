# plugins/slideshow_plugin.py

import os
import re
import yaml
import frontmatter
import subprocess
from flask import Blueprint, send_from_directory, current_app, url_for, abort
from werkzeug.utils import safe_join

# --- Configuration ---
SLIDESHOW_BLUEPRINT_NAME = 'slideshow_plugin'

# --- Blueprint ---
slideshow_bp = Blueprint(SLIDESHOW_BLUEPRINT_NAME, __name__)

# --- Helper Functions ---
def get_slideshow_path(app_instance, page_name):
    """Gets the full path to a generated slideshow HTML file."""
    slideshow_dir = app_instance.config.get('SLIDESHOW_DIR')
    if not slideshow_dir:
        app_instance.logger.error("Slideshow Plugin: SLIDESHOW_DIR is not configured!")
        return None
    return safe_join(slideshow_dir, page_name + '.html')

# --- Core Logic ---
def generate_slideshow(page_name, **kwargs):
    """
    Converts a page's Markdown file to a Marp HTML slideshow,
    injecting the custom font palette.
    """
    source_file_path = kwargs.get('file_path')
    app_context = kwargs.get('app_context', current_app)

    if not source_file_path:
        app_context.logger.error("Slideshow Plugin: 'file_path' not provided.")
        return

    app_context.logger.info(f"Slideshow Plugin: Generating slideshow for '{page_name}'.")
    
    slideshow_output_path = get_slideshow_path(app_context, page_name)
    if not slideshow_output_path:
        return

    os.makedirs(os.path.dirname(slideshow_output_path), exist_ok=True)

    try:
        with open(source_file_path, 'r', encoding='utf-8') as f:
            article = frontmatter.load(f)

        article.content = article.content.replace('~~SLIDESHOW~~', '')
        
        # --- NEW: Define and inject the custom font styles ---
        # This CSS will be injected by Marp into the <style> tag of the final HTML.
        font_styles = """
@import url('https://fonts.googleapis.com/css2?family=Karla:wght@700&family=Tinos:ital,wght@0,400;0,700;1,400&family=VT323&display=swap');

section { /* Targets the body of each slide */
  font-family: 'Tinos', 'Times New Roman', serif;
  font-size: 1.1em; /* Slightly increase base font size for slides */
  line-height: 1.6;
}
section h1, section h2, section h3 {
  font-family: 'Karla', sans-serif;
}
section pre, section code, section kbd, section samp {
  font-family: 'VT323', monospace;
}
"""
        
        # Set Marp directives, including our new custom style block.
        article.metadata['marp'] = {
            'theme': 'uncover',
            'size': '16:9',
            'header': f"*{article.metadata.get('title', page_name)}*",
            'style': font_styles
        }
        
        # Re-assemble the full document with the modified frontmatter.
        full_document_string = frontmatter.dumps(article)
        
        # Insert slide dividers before every H2 for automatic slide breaks.
        final_markdown = re.sub(r'\n(## .*)', r'\n\n---\n\n\1', full_document_string)
        
        env = os.environ.copy()
        env['CHROME_NO_SANDBOX'] = 'true'

        subprocess.run(
            ['marp', '--html', '--allow-local-files', '--output', slideshow_output_path],
            input=final_markdown,
            text=True,
            capture_output=True,
            check=True,
            env=env
        )
        
        app_context.logger.info(f"Slideshow Plugin: Successfully created slideshow at {slideshow_output_path}")

    except Exception as e:
        app_context.logger.error(f"Slideshow Plugin: Failed to generate slideshow for '{page_name}': {e}", exc_info=True)


# --- Other Plugin Functions (Unchanged) ---
def delete_slideshow(page_name, **kwargs):
    app_context = kwargs.get('app_context', current_app)
    slideshow_path = get_slideshow_path(app_context, page_name)
    if slideshow_path and os.path.exists(slideshow_path):
        try: os.remove(slideshow_path)
        except Exception as e: app_context.logger.error(f"Slideshow Plugin: Failed to delete slideshow for '{page_name}': {e}")

@slideshow_bp.route('/slideshows/<path:page_name>.html')
def serve_slideshow(page_name):
    slideshow_dir = current_app.config.get('SLIDESHOW_DIR')
    if not slideshow_dir or not os.path.exists(os.path.join(slideshow_dir, page_name + '.html')):
        abort(404)
    return send_from_directory(slideshow_dir, page_name + '.html')

def process_slideshow_macro(markdown_content, current_page_slug, **kwargs):
    if '~~SLIDESHOW~~' not in markdown_content: return markdown_content
    app_context = kwargs.get('app_context', current_app)
    slideshow_path = get_slideshow_path(app_context, current_page_slug)
    if slideshow_path and os.path.exists(slideshow_path):
        url = url_for(f'{SLIDESHOW_BLUEPRINT_NAME}.serve_slideshow', page_name=current_page_slug)
        return markdown_content.replace('~~SLIDESHOW~~', f'<p class="slideshow-link"><a href="{url}" target="_blank" rel="noopener noreferrer">View as Slideshow</a></p>')
    else:
        return markdown_content.replace('~~SLIDESHOW~~', '<p class="slideshow-link"><em>Slideshow not yet generated. Please save the page again.</em></p>')

def register(app, register_hook):
    app.register_blueprint(slideshow_bp)
    register_hook('after_page_save', generate_slideshow)
    register_hook('after_page_delete', delete_slideshow)
    register_hook('process_page_macros', process_slideshow_macro)
    if app.config.get('SLIDESHOW_DIR'):
        os.makedirs(app.config['SLIDESHOW_DIR'], exist_ok=True)
    app.logger.info("Slideshow plugin with custom fonts registered.")
