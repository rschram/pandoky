# plugins/cluster_plugin.py

import os
import json
import numpy as np
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sklearn.feature_extraction import DictVectorizer
from sklearn.cluster import KMeans
from collections import defaultdict

# --- Configuration ---
CLUSTER_BLUEPRINT_NAME = 'cluster_plugin'
CONFIG_FILENAME = "cluster_config.json"
CLUSTER_DATA_FILENAME = "cluster_data.json"
# Filenames from the indexer plugin are now all needed
PAGE_META_FILENAME = "indexer_page_meta.json"
VECTORS_FILENAME = "indexer_tfidf_vectors.json"
VOCABULARY_FILENAME = "indexer_vocabulary.json"

# --- Blueprint for Admin Routes ---
cluster_bp = Blueprint(
    CLUSTER_BLUEPRINT_NAME,
    __name__,
    template_folder='../templates/html/admin'
)

# --- Helper Functions ---
def get_config_path(app_instance):
    return os.path.join(app_instance.config['DATA_DIR'], CONFIG_FILENAME)

def get_cluster_data_path(app_instance):
    return os.path.join(app_instance.config['DATA_DIR'], CLUSTER_DATA_FILENAME)

def load_config(app_instance):
    config_path = get_config_path(app_instance)
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'num_clusters': 5, 'num_top_terms': 3}

def save_config(app_instance, config_data):
    config_path = get_config_path(app_instance)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4)

def load_cluster_data(app_instance):
    cluster_data_path = get_cluster_data_path(app_instance)
    if os.path.exists(cluster_data_path):
        with open(cluster_data_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'clusters': {}, 'page_to_cluster': {}, 'cluster_names': {}}

# --- Core Clustering Logic ---
def run_clustering(app_instance, num_clusters, num_top_terms):
    data_dir = app_instance.config['DATA_DIR']
    vectors_path = os.path.join(data_dir, VECTORS_FILENAME)
    meta_path = os.path.join(data_dir, PAGE_META_FILENAME)
    vocab_path = os.path.join(data_dir, VOCABULARY_FILENAME)

    if not all(os.path.exists(p) for p in [vectors_path, meta_path, vocab_path]):
        flash("Could not find required index files (vectors, metadata, or vocabulary). Please run the indexer first.", "error")
        return False

    try:
        page_meta = load_json_data(app_instance, PAGE_META_FILENAME)
        all_vectors = load_json_data(app_instance, VECTORS_FILENAME)
        vocabulary = load_json_data(app_instance, VOCABULARY_FILENAME)
        id_to_word = vocabulary.get("id_to_word", {})
        
        page_ids_sorted = sorted(all_vectors.keys(), key=int)
        vector_list = [all_vectors[pid] for pid in page_ids_sorted]

        if not vector_list:
            flash("No page data found to cluster.", "error")
            return False

        vectorizer = DictVectorizer(sparse=True)
        tfidf_matrix = vectorizer.fit_transform(vector_list)
        
        id_to_slug = page_meta.get("id_to_slug", {})
        page_slugs = [id_to_slug.get(pid) for pid in page_ids_sorted]

    except Exception as e:
        flash(f"Error loading or processing TF-IDF data: {e}", "error")
        return False

    if tfidf_matrix.shape[0] < num_clusters:
        flash(f"Cannot create {num_clusters} clusters with only {tfidf_matrix.shape[0]} pages.", "error")
        return False
        
    kmeans = KMeans(n_clusters=num_clusters, random_state=42, n_init=10)
    kmeans.fit(tfidf_matrix)
    
    # --- Cluster Naming Logic ---
    cluster_names = {}
    feature_names = vectorizer.get_feature_names_out() 
    centroids = kmeans.cluster_centers_
    top_term_indices = centroids.argsort()[:, ::-1][:, :num_top_terms]
    
    for i, top_indices in enumerate(top_term_indices):
        cluster_id_str = str(i)
        top_words = []
        for term_index in top_indices:
            word_id = feature_names[term_index]
            word = id_to_word.get(str(word_id), "unknown")
            top_words.append(word.capitalize())
        cluster_names[cluster_id_str] = " - ".join(top_words)

    clusters = defaultdict(list)
    page_to_cluster = {}
    for i, label in enumerate(kmeans.labels_):
        page_slug = page_slugs[i]
        if not page_slug: continue
        cluster_id = str(label)
        clusters[cluster_id].append(page_slug)
        page_to_cluster[page_slug] = cluster_id

    # Save all data including the new names
    with open(get_cluster_data_path(app_instance), 'w', encoding='utf-8') as f:
        json.dump({
            'clusters': clusters, 
            'page_to_cluster': page_to_cluster, 
            'cluster_names': cluster_names
        }, f, indent=4)
    
    flash(f"Successfully clustered pages and generated names for {num_clusters} clusters.", "success")
    return True

# --- Admin Route ---
@cluster_bp.route('/admin/clustering', methods=['GET', 'POST'])
def clustering_admin_page():
    if request.method == 'POST':
        num_clusters = int(request.form.get('num_clusters', 5))
        num_top_terms = int(request.form.get('num_top_terms', 3))
        save_config(current_app, {'num_clusters': num_clusters, 'num_top_terms': num_top_terms})
        run_clustering(current_app, num_clusters, num_top_terms)
        return redirect(url_for(f'{CLUSTER_BLUEPRINT_NAME}.clustering_admin_page'))

    config = load_config(current_app)
    cluster_data = load_cluster_data(current_app)
    return render_template('clustering_admin.html', title="Content Clustering", config=config, cluster_data=cluster_data)


# --- Macro Processing ---
def generate_full_cluster_list(app_instance):
    cluster_data = load_cluster_data(app_instance)
    all_clusters = cluster_data.get('clusters', {})
    cluster_names = cluster_data.get('cluster_names', {})

    if not all_clusters:
        return "*No clusters have been generated yet.*"
    
    output_md_parts = []
    for cluster_id in sorted(all_clusters.keys(), key=int):
        cluster_name = cluster_names.get(cluster_id, f"Cluster {cluster_id}")
        output_md_parts.append(f"### {cluster_name}")
        
        pages_in_cluster = sorted(all_clusters[cluster_id])
        for page_slug in pages_in_cluster:
            display_name = page_slug.replace('/', ' / ').replace('-', ' ').title()
            output_md_parts.append(f"* [[{page_slug}|{display_name}]]")
        output_md_parts.append("")

    return "\n".join(output_md_parts)

def process_cluster_macros(markdown_content, current_page_slug, **kwargs):
    app_instance = kwargs.get('app_context', current_app)
    
    if '~~CLUSTER_MEMBERS~~' in markdown_content:
        cluster_data = load_cluster_data(app_instance)
        page_to_cluster = cluster_data.get('page_to_cluster', {})
        current_cluster_id = page_to_cluster.get(current_page_slug)
        replacement_md = ""
        if current_cluster_id is not None:
            cluster_members = cluster_data.get('clusters', {}).get(current_cluster_id, [])
            list_items = [f"* [[{ps}|{ps.replace('/', ' / ').replace('-', ' ').title()}]]" 
                          for ps in sorted(cluster_members) if ps != current_page_slug]
            replacement_md = "\n".join(list_items) if list_items else "*No other pages found in this cluster.*"
        else:
            replacement_md = '*This page has not been clustered yet.*'
        markdown_content = markdown_content.replace('~~CLUSTER_MEMBERS~~', replacement_md)

    if '~~CLUSTER_LIST~~' in markdown_content:
        full_list_md = generate_full_cluster_list(app_instance)
        markdown_content = markdown_content.replace('~~CLUSTER_LIST~~', full_list_md)

    return markdown_content

# --- Plugin Registration ---
def register(app, register_hook):
    app.register_blueprint(cluster_bp)
    register_hook('process_page_macros', process_cluster_macros)

    if not os.path.exists(get_config_path(app)):
        save_config(app, {'num_clusters': 5, 'num_top_terms': 3})
    if not os.path.exists(get_cluster_data_path(app)):
        with open(get_cluster_data_path(app), 'w') as f:
            json.dump({'clusters': {}, 'page_to_cluster': {}, 'cluster_names': {}}, f)

    app.logger.info("Cluster Naming plugin registered.")
