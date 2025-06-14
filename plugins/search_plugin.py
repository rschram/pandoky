# pandoky/plugins/search_plugin.py

import os
import json
import re
from collections import defaultdict, Counter
from flask import request, render_template, url_for, current_app
import frontmatter

# --- Configuration (relative to the indexer plugin's filenames) ---
PAGE_META_FILENAME = "indexer_page_meta.json"
VOCABULARY_FILENAME = "indexer_vocabulary.json"
INVERTED_INDEX_FILENAME = "indexer_inverted_index.json"

# --- Helper Functions ---

def get_data_file_path(app_instance, filename):
    """Constructs the full path for a data file within the app's DATA_DIR."""
    data_dir = app_instance.config.get('DATA_DIR', os.path.join(app_instance.root_path, 'data'))
    return os.path.join(data_dir, filename)

def load_json_data(app_instance, filename, default_data=None):
    """Loads data from a JSON file. Returns default_data if file not found or error."""
    if default_data is None:
        default_data = {}
    file_path = get_data_file_path(app_instance, filename)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            app_instance.logger.error(f"SearchPlugin: Error loading {file_path}: {e}")
            return default_data
    return default_data

def tokenize_and_normalize_query(query_string):
    """Tokenizes and normalizes a search query string."""
    if not query_string:
        return []
    return re.findall(r'\b\w+\b', query_string.lower())

# --- Search Logic ---

def perform_search(app_instance, query_string):
    """
    Performs a search based on the query_string.
    Returns a list of result dictionaries.
    """
    if not query_string:
        return []

    app_instance.logger.info(f"SearchPlugin: Performing search for query: '{query_string}'")

    page_meta = load_json_data(app_instance, PAGE_META_FILENAME)
    vocabulary = load_json_data(app_instance, VOCABULARY_FILENAME)
    inverted_index = load_json_data(app_instance, INVERTED_INDEX_FILENAME)

    query_terms = tokenize_and_normalize_query(query_string)
    if not query_terms:
        return []

    query_word_ids = [vocabulary["word_to_id"][term] for term in query_terms if term in vocabulary.get("word_to_id", {})]

    if not query_word_ids:
        return []

    page_scores = defaultdict(float)
    for word_id in query_word_ids:
        word_id_str = str(word_id)
        if word_id_str in inverted_index:
            for posting in inverted_index[word_id_str]:
                page_id = posting.get("page_id")
                tf = posting.get("tf", 0)
                page_scores[page_id] += tf

    if not page_scores:
        return []

    results = []
    for page_id, score in page_scores.items():
        page_id_str = str(page_id)
        if page_id_str in page_meta.get("id_to_slug", {}):
            slug = page_meta["id_to_slug"][page_id_str]
            page_title = slug.replace('-', ' ').title() # Default title
            try:
                page_file_path = os.path.join(app_instance.config['PAGES_DIR'], slug + '.md')
                if os.path.exists(page_file_path):
                    with open(page_file_path, 'r', encoding='utf-8') as f:
                        article_fm = frontmatter.load(f)
                        page_title = article_fm.metadata.get('title', page_title)
            except Exception as e:
                app_instance.logger.warning(f"SearchPlugin: Could not read title for page {slug}: {e}")
            
            results.append({
                "slug": slug,
                "title": page_title,
                "score": score,
                "url": url_for('view_page', page_name=slug)
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# --- Flask Route for Search ---
# This is the main logic function for the search page.
def search_page_logic(app_instance):
    query = ""
    # Handle GET request (from nav bar or direct URL)
    if request.method == 'GET':
        query = request.args.get('query', '').strip()
    # Handle POST request (from the form on the search page itself)
    elif request.method == 'POST':
        query = request.form.get('query', '').strip()

    results = []
    if query:
        results = perform_search(app_instance, query)
        
    return render_template('html/search_results.html', query=query, results=results)


# --- Plugin Registration ---
def register(app_instance, register_hook_func):
    """Registers the plugin's routes with the Pandoky application."""
    
    # CORRECTED: Allow both GET and POST methods for the search route
    @app_instance.route('/search', methods=['GET', 'POST'])
    def bound_search_route():
        # The logic is now in a separate function for clarity
        return search_page_logic(app_instance)

    app_instance.logger.info("SearchPlugin: Registered /search route for GET and POST.")

