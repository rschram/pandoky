# pandoky/plugins/fulltext_indexer.py

import os
import json
import re
import math # For TF-IDF calculation (log)
from collections import Counter
import frontmatter # To parse frontmatter from page content
import pypandoc # For converting Markdown to plain text
# from flask import current_app # For potential direct app context if needed outside hooks

# --- Configuration ---
# File names for storing index data
PAGE_META_FILENAME = "indexer_page_meta.json"
VOCABULARY_FILENAME = "indexer_vocabulary.json"
INVERTED_INDEX_FILENAME = "indexer_inverted_index.json"
TFIDF_VECTORS_FILENAME = "indexer_tfidf_vectors.json" 

# --- Helper Functions for Data File Management ---

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
        except json.JSONDecodeError:
            app_instance.logger.error(f"IndexerPlugin: Error decoding JSON from {file_path}")
            return default_data
        except Exception as e:
            app_instance.logger.error(f"IndexerPlugin: Error loading {file_path}: {e}")
            return default_data
    return default_data

def save_json_data(app_instance, filename, data):
    """Saves data to a JSON file."""
    file_path = get_data_file_path(app_instance, filename)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        app_instance.logger.info(f"IndexerPlugin: Data saved to {file_path}") 
    except Exception as e:
        app_instance.logger.error(f"IndexerPlugin: Error saving data to {file_path}: {e}")

# --- Page Metadata Management ---

def get_or_create_page_id(app_instance, page_slug):
    """Gets existing page_id for a slug, or creates a new one."""
    meta_data = load_json_data(app_instance, PAGE_META_FILENAME, 
                               default_data={"next_page_id": 0, "slug_to_id": {}, "id_to_slug": {}})
    if page_slug not in meta_data["slug_to_id"]:
        page_id = meta_data["next_page_id"]
        meta_data["slug_to_id"][page_slug] = page_id
        meta_data["id_to_slug"][str(page_id)] = page_slug 
        meta_data["next_page_id"] += 1
        save_json_data(app_instance, PAGE_META_FILENAME, meta_data)
        app_instance.logger.info(f"IndexerPlugin: Assigned new page_id {page_id} to slug '{page_slug}'")
        return page_id
    return meta_data["slug_to_id"][page_slug]

def remove_page_meta(app_instance, page_slug):
    """Removes page metadata."""
    meta_data = load_json_data(app_instance, PAGE_META_FILENAME)
    if page_slug in meta_data.get("slug_to_id", {}):
        page_id = meta_data["slug_to_id"].pop(page_slug)
        meta_data.get("id_to_slug", {}).pop(str(page_id), None) 
        save_json_data(app_instance, PAGE_META_FILENAME, meta_data)
        app_instance.logger.info(f"IndexerPlugin: Removed metadata for page_slug '{page_slug}' (ID: {page_id})")
        return page_id
    return None

# --- Vocabulary Management ---

def get_or_create_word_id(app_instance, word):
    """Gets existing word_id for a word, or creates a new one."""
    vocab_data = load_json_data(app_instance, VOCABULARY_FILENAME,
                                default_data={"next_word_id": 0, "word_to_id": {}, "id_to_word": {}})
    if word not in vocab_data["word_to_id"]:
        word_id = vocab_data["next_word_id"]
        vocab_data["word_to_id"][word] = word_id
        vocab_data["id_to_word"][str(word_id)] = word 
        vocab_data["next_word_id"] += 1
        save_json_data(app_instance, VOCABULARY_FILENAME, vocab_data)
        return word_id
    return vocab_data["word_to_id"][word]

# --- Text Processing ---

def extract_text_from_markdown(app_instance, markdown_content):
    """Converts Markdown to plain text using Pandoc."""
    try:
        plain_text = pypandoc.convert_text(markdown_content, 'plain', format='markdown')
        return plain_text
    except Exception as e:
        app_instance.logger.error(f"IndexerPlugin: Error converting Markdown to plain text with Pandoc: {e}")
        return "" 

def tokenize_and_normalize(text_content):
    """Tokenizes text, converts to lowercase."""
    if not text_content:
        return []
    words = re.findall(r'\b\w+\b', text_content.lower())
    return words

# --- Indexing Logic ---

def update_inverted_index(app_instance, page_id, word_id_tf_map):
    """
    Updates the inverted index for a given page.
    word_id_tf_map is a dict: {word_id: term_frequency} for the current page.
    """
    inverted_index = load_json_data(app_instance, INVERTED_INDEX_FILENAME, default_data={})

    for word_id_str in list(inverted_index.keys()): 
        postings = inverted_index[word_id_str]
        inverted_index[word_id_str] = [post for post in postings if post.get("page_id") != page_id]
        if not inverted_index[word_id_str]:
            del inverted_index[word_id_str]
            
    for word_id, tf in word_id_tf_map.items():
        word_id_str = str(word_id) 
        if word_id_str not in inverted_index:
            inverted_index[word_id_str] = []
        inverted_index[word_id_str].append({"page_id": page_id, "tf": tf})

    save_json_data(app_instance, INVERTED_INDEX_FILENAME, inverted_index)

def remove_from_inverted_index(app_instance, page_id):
    """Removes all postings for a given page_id from the inverted index."""
    inverted_index = load_json_data(app_instance, INVERTED_INDEX_FILENAME, default_data={})
    updated_index = {}
    changed = False

    for word_id_str, postings in inverted_index.items():
        original_length = len(postings)
        new_postings = [post for post in postings if post.get("page_id") != page_id]
        if len(new_postings) < original_length:
            changed = True
        if new_postings: 
            updated_index[word_id_str] = new_postings
    
    if changed:
        save_json_data(app_instance, INVERTED_INDEX_FILENAME, updated_index)
        app_instance.logger.info(f"IndexerPlugin: Removed page_id {page_id} from inverted index.")

# --- TF-IDF Calculation and Storage ---
def calculate_and_store_tfidf_vector(app_instance, page_id, word_id_tf_map_for_page, 
                                     global_inverted_index=None, total_documents_in_collection=None):
    """
    Calculates TF-IDF vector for a page and stores it.
    Can accept pre-loaded global_inverted_index and total_documents for batch processing.
    """
    app_instance.logger.info(f"IndexerPlugin: Calculating TF-IDF for page_id {page_id}")

    if global_inverted_index is None:
        global_inverted_index = load_json_data(app_instance, INVERTED_INDEX_FILENAME)
    
    if total_documents_in_collection is None:
        page_meta = load_json_data(app_instance, PAGE_META_FILENAME)
        total_documents_in_collection = len(page_meta.get("slug_to_id", {}))

    if total_documents_in_collection == 0:
        app_instance.logger.warning("IndexerPlugin: No documents in collection, TF-IDF vector will be empty.")
        # Store an empty vector
        tfidf_vectors_data = load_json_data(app_instance, TFIDF_VECTORS_FILENAME, default_data={})
        tfidf_vectors_data[str(page_id)] = {}
        save_json_data(app_instance, TFIDF_VECTORS_FILENAME, tfidf_vectors_data)
        return {} # Return the empty vector

    document_frequency_map = {} # Stores df for terms in the current page
    for word_id in word_id_tf_map_for_page.keys():
        word_id_str = str(word_id)
        if word_id_str in global_inverted_index:
            document_frequency_map[word_id] = len(global_inverted_index[word_id_str])
        else:
            # If a term from the current page is not in the global inverted index yet
            # (e.g., during a full rebuild before this page's terms are added to global_inverted_index),
            # its df is effectively 1 for this calculation.
            document_frequency_map[word_id] = 1 

    current_page_tfidf_vector = {}
    for word_id, tf in word_id_tf_map_for_page.items():
        df = document_frequency_map.get(word_id, 1) 
        if df > 0 and total_documents_in_collection > 0 : # Ensure N > 0
             idf = math.log(total_documents_in_collection / df) # Basic IDF
        else: # Avoid log(0) or division by zero if N=0 or df=0 (though df should be >=1 here)
             idf = 0.0 

        current_page_tfidf_vector[str(word_id)] = tf * idf
    
    # This function now returns the vector; saving is done by the caller (recalculate_all or index_page_on_save)
    return current_page_tfidf_vector


def remove_tfidf_vector(app_instance, page_id):
    """Removes the TF-IDF vector for a given page_id."""
    tfidf_vectors = load_json_data(app_instance, TFIDF_VECTORS_FILENAME, default_data={})
    page_id_str = str(page_id)
    if page_id_str in tfidf_vectors:
        del tfidf_vectors[page_id_str]
        save_json_data(app_instance, TFIDF_VECTORS_FILENAME, tfidf_vectors)
        app_instance.logger.info(f"IndexerPlugin: Removed TF-IDF vector for page_id {page_id}.")

# --- NEW: Full TF-IDF Recalculation ---
def recalculate_all_tfidf_vectors(app_instance, trigger_hook_func=None):
    """
    Recalculates TF-IDF vectors for all pages in the collection.
    This is an expensive operation and should be run periodically or manually.
    """
    app_instance.logger.info("IndexerPlugin: Starting full recalculation of all TF-IDF vectors.")

    page_meta = load_json_data(app_instance, PAGE_META_FILENAME)
    vocabulary = load_json_data(app_instance, VOCABULARY_FILENAME) # Needed if we re-tokenize
    global_inverted_index = load_json_data(app_instance, INVERTED_INDEX_FILENAME)
    
    all_page_slugs_to_ids = page_meta.get("slug_to_id", {})
    total_documents_in_collection = len(all_page_slugs_to_ids)

    if total_documents_in_collection == 0:
        app_instance.logger.info("IndexerPlugin: No pages to recalculate TF-IDF for.")
        save_json_data(app_instance, TFIDF_VECTORS_FILENAME, {}) # Ensure it's empty
        return

    new_tfidf_vectors_collection = {}
    processed_count = 0

    for page_slug, page_id in all_page_slugs_to_ids.items():
        app_instance.logger.debug(f"IndexerPlugin: Recalculating TF-IDF for page_slug '{page_slug}' (ID: {page_id})")
        if 'PAGES_DIR_BASENAME' in app_instance.config: 
            page_file_path = get_data_file_path(app_instance, os.path.join(app_instance.config['PAGES_DIR_BASENAME'], page_slug + '.md'))
        else: 
            page_file_path = os.path.join(app_instance.config['PAGES_DIR'], page_slug + '.md')


        if not os.path.exists(page_file_path):
            app_instance.logger.warning(f"IndexerPlugin: File for page_slug '{page_slug}' not found at '{page_file_path}'. Skipping TF-IDF recalculation for this page.")
            continue

        try:
            with open(page_file_path, 'r', encoding='utf-8') as f:
                raw_page_content = f.read()
            
            article = frontmatter.loads(raw_page_content)
            markdown_body = article.content
            plain_text_body = extract_text_from_markdown(app_instance, markdown_body)
            tokens = tokenize_and_normalize(plain_text_body)
            term_frequencies_for_page = Counter(tokens)

            word_id_tf_map_for_page = {}
            for word, tf in term_frequencies_for_page.items():
                if not word: continue
                # Use existing vocabulary; do not create new word_ids during a recalculation pass
                # as vocabulary should be stable or managed by the regular indexing process.
                if word in vocabulary.get("word_to_id", {}):
                    word_id = vocabulary["word_to_id"][word]
                    word_id_tf_map_for_page[word_id] = tf
                else:
                    app_instance.logger.debug(f"IndexerPlugin: Word '{word}' from page '{page_slug}' not in vocabulary during TF-IDF recalc. Skipping this word for TF-IDF.")

            if word_id_tf_map_for_page:
                page_tfidf_vector = calculate_and_store_tfidf_vector(
                    app_instance, 
                    page_id, 
                    word_id_tf_map_for_page,
                    global_inverted_index, # Pass pre-loaded global index
                    total_documents_in_collection # Pass pre-calculated total docs
                )
                new_tfidf_vectors_collection[str(page_id)] = page_tfidf_vector
            else:
                new_tfidf_vectors_collection[str(page_id)] = {} # Empty vector if no relevant terms
            
            processed_count +=1
        except Exception as e:
            app_instance.logger.error(f"IndexerPlugin: Error recalculating TF-IDF for page '{page_slug}': {e}", exc_info=True)

    # Save the complete new collection of TF-IDF vectors
    save_json_data(app_instance, TFIDF_VECTORS_FILENAME, new_tfidf_vectors_collection)
    app_instance.logger.info(f"IndexerPlugin: Full recalculation of TF-IDF vectors complete. Processed {processed_count}/{total_documents_in_collection} pages.")

    if trigger_hook_func: # If a trigger_hook function is passed (e.g., from main app)
        trigger_hook_func('recalculate_tfidf_hook_completed', app_context=app_instance, count=processed_count)


# --- Hook Functions ---

def index_page_on_save(page_name_slug, file_path, app_context):
    """Hook function called after a page is saved."""
    app_context.logger.info(f"IndexerPlugin (HOOK: after_page_save): Processing page '{page_name_slug}' from '{file_path}'")
    try:
        page_id = get_or_create_page_id(app_context, page_name_slug)
        app_context.logger.info(f"IndexerPlugin: Page ID for '{page_name_slug}' is {page_id}.")

        if not os.path.exists(file_path):
            app_context.logger.warning(f"IndexerPlugin: File '{file_path}' not found for page '{page_name_slug}'. Cannot index.")
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            raw_page_content = f.read()
        
        article = frontmatter.loads(raw_page_content)
        markdown_body = article.content
        
        plain_text_body = extract_text_from_markdown(app_context, markdown_body)
        tokens = tokenize_and_normalize(plain_text_body)
        
        term_frequencies_for_page = Counter(tokens)
        word_id_tf_map_for_page = {} 
        for word, tf in term_frequencies_for_page.items():
            if not word: continue 
            word_id = get_or_create_word_id(app_context, word)
            word_id_tf_map_for_page[word_id] = tf
        
        update_inverted_index(app_context, page_id, word_id_tf_map_for_page)
        app_context.logger.info(f"IndexerPlugin: Updated inverted index for page '{page_name_slug}' (ID: {page_id}).")

        # Calculate and store TF-IDF vector for THIS page
        # This uses the current global inverted index and total doc count for IDF calculation
        page_tfidf_vector = calculate_and_store_tfidf_vector(app_context, page_id, word_id_tf_map_for_page)
        # Save this single page's TF-IDF vector
        tfidf_vectors_data = load_json_data(app_context, TFIDF_VECTORS_FILENAME, default_data={})
        tfidf_vectors_data[str(page_id)] = page_tfidf_vector
        save_json_data(app_context, TFIDF_VECTORS_FILENAME, tfidf_vectors_data)

        app_context.logger.info(f"IndexerPlugin: Indexing and TF-IDF calculation complete for page '{page_name_slug}'.")

    except Exception as e:
        app_context.logger.error(f"IndexerPlugin: Unhandled error in index_page_on_save for '{page_name_slug}': {e}", exc_info=True)

def deindex_page_on_delete(page_name_slug, file_path, app_context):
    """Hook function called after a page is deleted."""
    app_context.logger.info(f"IndexerPlugin (HOOK: after_page_delete): Processing page '{page_name_slug}' for de-indexing.")
    try:
        meta_data = load_json_data(app_context, PAGE_META_FILENAME)
        page_id = meta_data.get("slug_to_id", {}).get(page_name_slug)

        if page_id is not None:
            remove_from_inverted_index(app_context, page_id)
            remove_tfidf_vector(app_context, page_id) 
            remove_page_meta(app_context, page_name_slug) 
            app_context.logger.info(f"IndexerPlugin: Successfully de-indexed page '{page_name_slug}' (ID: {page_id}).")
            # Note: Deleting a page changes total_documents and potentially document_frequencies.
            # A full TF-IDF recalculation for all other pages might be needed for perfect accuracy.
        else:
            app_context.logger.warning(f"IndexerPlugin: Page slug '{page_name_slug}' not found in metadata for de-indexing.")

    except Exception as e:
        app_context.logger.error(f"IndexerPlugin: Error de-indexing page '{page_name_slug}': {e}", exc_info=True)


# --- Plugin Registration ---
def register(app_instance, register_hook_func):
    """Registers the plugin's hooks with the Pandoky application."""

    def index_page_on_save_with_context(page_name, file_path, **kwargs):
        actual_app_context = kwargs.get('app_context', app_instance) 
        app_instance.logger.debug(f"IndexerPlugin: index_page_on_save_with_context called for page '{page_name}'")
        index_page_on_save(page_name, file_path, app_context=actual_app_context)

    def deindex_page_on_delete_with_context(page_name, file_path, **kwargs):
        actual_app_context = kwargs.get('app_context', app_instance)
        app_instance.logger.debug(f"IndexerPlugin: deindex_page_on_delete_with_context called for page '{page_name}'")
        deindex_page_on_delete(page_name, file_path, app_context=actual_app_context)

    register_hook_func('after_page_save', index_page_on_save_with_context)
    register_hook_func('after_page_delete', deindex_page_on_delete_with_context)
    
    app_instance.logger.info("AdvancedFullTextIndexer plugin (with TF-IDF) registered.")

    # Initialize data files if they don't exist on app start
    for filename, default_content in [
        (PAGE_META_FILENAME, {"next_page_id": 0, "slug_to_id": {}, "id_to_slug": {}}),
        (VOCABULARY_FILENAME, {"next_word_id": 0, "word_to_id": {}, "id_to_word": {}}),
        (INVERTED_INDEX_FILENAME, {}),
        (TFIDF_VECTORS_FILENAME, {}) 
    ]:
        file_path = get_data_file_path(app_instance, filename)
        if not os.path.exists(file_path):
            app_instance.logger.info(f"IndexerPlugin: Data file '{filename}' not found. Creating empty file.")
            save_json_data(app_instance, filename, default_content)
            
    def _recalculate_all_tfidf_vectors_callable():
        main_app_trigger_hook = getattr(app_instance, 'trigger_hook', None)
        if main_app_trigger_hook is None:
            app_instance.logger.warning("IndexerPlugin: Main app's trigger_hook not found on app_instance. Recalculation hooks won't be triggered.")
        recalculate_all_tfidf_vectors(app_instance, main_app_trigger_hook)

    app_instance.recalculate_all_tfidf = _recalculate_all_tfidf_vectors_callable
    app_instance.logger.info("IndexerPlugin: Made 'recalculate_all_tfidf' available on app instance.")
    
