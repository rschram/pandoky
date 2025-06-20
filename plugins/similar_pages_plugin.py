# pandoky/plugins/similar_pages_plugin.py

import os
import json
import re
import math
from flask import url_for # For generating links

# --- Configuration (filenames from fulltext_indexer.py) ---
# These assume the fulltext_indexer.py plugin uses these exact names
# and that this plugin can access them via the app_instance.
PAGE_META_FILENAME = "indexer_page_meta.json"
TFIDF_VECTORS_FILENAME = "indexer_tfidf_vectors.json"
# VOCABULARY_FILENAME = "indexer_vocabulary.json" # Not directly needed for this version

# --- Helper Functions ---
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
            app_instance.logger.error(f"SimilarPagesPlugin: Error decoding JSON from {file_path}")
        except Exception as e:
            app_instance.logger.error(f"SimilarPagesPlugin: Error loading {file_path}: {e}")
    return default_data

def cosine_similarity(vec1, vec2):
    """Calculates cosine similarity between two TF-IDF vectors (dicts of word_id: score)."""
    # Find common word_ids (intersection of keys)
    # Convert keys to int for comparison if they are strings in the dict
    vec1_keys = {int(k) for k in vec1.keys()}
    vec2_keys = {int(k) for k in vec2.keys()}
    intersection = vec1_keys & vec2_keys

    if not intersection:
        return 0.0
    
    dot_product = sum(vec1[str(x)] * vec2[str(x)] for x in intersection)
    
    sum_sq_vec1 = sum(vec1[str(x)]**2 for x in vec1_keys)
    sum_sq_vec2 = sum(vec2[str(x)]**2 for x in vec2_keys)
    
    magnitude_vec1 = math.sqrt(sum_sq_vec1)
    magnitude_vec2 = math.sqrt(sum_sq_vec2)
    
    if magnitude_vec1 == 0 or magnitude_vec2 == 0:
        return 0.0
    
    return dot_product / (magnitude_vec1 * magnitude_vec2)

# --- Macro Processing ---
def generate_similar_pages_html(app_instance, current_page_slug, num_similar=5):
    """
    Generates an HTML list of pages similar to the current page.
    """
    app_instance.logger.debug(f"SimilarPagesPlugin: Generating similar pages for '{current_page_slug}', N={num_similar}")

    page_meta = load_json_data(app_instance, PAGE_META_FILENAME)
    all_tfidf_vectors = load_json_data(app_instance, TFIDF_VECTORS_FILENAME)

    slug_to_id = page_meta.get("slug_to_id", {})
    id_to_slug = page_meta.get("id_to_slug", {})

    current_page_id_str = str(slug_to_id.get(current_page_slug))
    if not current_page_id_str or current_page_id_str not in all_tfidf_vectors:
        app_instance.logger.warning(f"SimilarPagesPlugin: TF-IDF vector for current page '{current_page_slug}' (ID: {current_page_id_str}) not found.")
        return "<!-- Similar pages data not available for this page. -->"

    current_vector = all_tfidf_vectors[current_page_id_str]
    if not current_vector: # Empty vector
        app_instance.logger.info(f"SimilarPagesPlugin: Current page '{current_page_slug}' has an empty TF-IDF vector. No similarities can be computed.")
        return "<!-- No content to compare for similar pages. -->"

    similarities = []
    for page_id_str, other_vector in all_tfidf_vectors.items():
        if page_id_str == current_page_id_str or not other_vector: # Skip self or empty vectors
            continue
        
        similarity_score = cosine_similarity(current_vector, other_vector)
        if similarity_score > 0: # Only consider pages with some similarity
            similarities.append((page_id_str, similarity_score))

    if not similarities:
        return "<!-- No similar pages found. -->"

    # Sort by similarity score in descending order
    similarities.sort(key=lambda item: item[1], reverse=True)
    
    top_n_similar = similarities[:num_similar]

    if not top_n_similar:
        return "<!-- No similar pages found above threshold. -->"

    html_list = '<ul class="similar-pages-list">\n'
    for page_id_str, score in top_n_similar:
        similar_page_slug = id_to_slug.get(page_id_str)
        if similar_page_slug:
            # For title, ideally fetch from page_meta if stored, or read file (slow)
            # For now, use a cleaned-up slug as title.
            # A better approach: indexer plugin stores titles in page_meta.json
            page_title = similar_page_slug.replace('-', ' ').replace('/', ' / ').title()
            page_url = url_for('view_page', page_name=similar_page_slug) # Assumes 'view_page' is the main app's route
            percentage_score = score * 100
            html_list += f'  <li><a href="{page_url}">{page_title}</a> (Similarity: {percentage_score:.0f}%)</li>\n'
    html_list += '</ul>\n'
    
    return html_list

def process_similar_macro_hook(markdown_content, current_page_slug, app_context):
    """
    Hook function to find and replace ~~SIMILAR(N)~~ macros.
    `app_context` is the Flask app instance.
    """
    app_context.logger.debug(f"SimilarPagesPlugin (HOOK: process_page_macros) for page '{current_page_slug}'")

    # Regex to find ~~SIMILAR~~ or ~~SIMILAR(N)~~
    # It captures the optional number N.
    macro_pattern = r'~~\s*SIMILAR(?:\s*\((\d+)\))?\s*~~'

    def replace_macro(match):
        num_similar_str = match.group(1)
        num_similar = 5 # Default
        if num_similar_str:
            try:
                num_similar = int(num_similar_str)
                if num_similar <= 0:
                    num_similar = 5 # Fallback to default if invalid number
            except ValueError:
                app_context.logger.warning(f"SimilarPagesPlugin: Invalid number '{num_similar_str}' in SIMILAR macro. Using default {num_similar}.")
        
        return generate_similar_pages_html(app_context, current_page_slug, num_similar)

    # Perform the substitution
    # We use a function for re.sub to handle multiple occurrences correctly
    new_content, num_replacements = re.subn(macro_pattern, replace_macro, markdown_content)
    
    if num_replacements > 0:
        app_context.logger.info(f"SimilarPagesPlugin: Replaced {num_replacements} SIMILAR macro(s) on page '{current_page_slug}'.")
        return new_content
    else:
        return markdown_content # Return original if no macro found

# --- Plugin Registration ---
def register(app_instance, register_hook_func):
    """Registers the Similar Pages plugin."""

    # Ensure the indexer plugin's data files exist (optional check, indexer should create them)
    # This is more of a dependency check.
    if not os.path.exists(get_data_file_path(app_instance, TFIDF_VECTORS_FILENAME)) or \
       not os.path.exists(get_data_file_path(app_instance, PAGE_META_FILENAME)):
        app_instance.logger.warning("SimilarPagesPlugin: Indexer data files (TFIDF vectors or Page Meta) not found. Similar pages functionality might be limited.")

    # Wrapper for the hook function to ensure app_context is passed correctly
    def _process_similar_macro_hook_wrapper(markdown_content, current_page_slug, **kwargs):
        # app_context is passed by trigger_hook from app.py
        # Use kwargs.get to safely access it, falling back to app_instance from closure if needed
        # though app_context passed by trigger_hook should be preferred.
        actual_app_context = kwargs.get('app_context', app_instance)
        return process_similar_macro_hook(markdown_content, current_page_slug, app_context=actual_app_context)

    # Register for the new 'process_page_macros' hook
    register_hook_func('process_page_macros', _process_similar_macro_hook_wrapper)
    
    app_instance.logger.info("SimilarPagesPlugin registered for 'process_page_macros' hook.")

